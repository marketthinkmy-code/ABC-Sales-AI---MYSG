"""
每日優化 (CPA-first) — 讀 config/optimization_rules.yaml,依『成交(CPA)』而非只看 CPL 判定。

流程:
  1. 拉近 N 天(OPTIMIZE_WINDOW_DAYS,預設 30)每個 ACTIVE campaign 的 花費 + 報名。
  2. 從 Stripe 買單 Sheet 撈同一視窗的成交,依 campaign 對回去 → 每支的 買單/CPA/ROAS。
  3. 套用規則(顯著性門檻 + CPA 目標):SCALE / KEEP / CUT / FUND / PAUSE / SKIP。
  4. DRY_RUN=true 只印建議不動手(規則檔預設 true)。

為什麼是 30 天而不是 3 天:買單在報名後幾天才發生,3 天視窗看不到成交、算不出 CPA。

用法: python optimize.py
env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, GOOGLE_SA_JSON, OPTIMIZE_WINDOW_DAYS(選填)
"""
import os, datetime as dt
from collections import defaultdict
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from spend_audit import read_buyers, norm, _is_reg

WINDOW = int(os.environ.get("OPTIMIZE_WINDOW_DAYS") or 30)
RULES_PATH = os.path.join(C.ROOT, "config", "optimization_rules.yaml")


def load_rules():
    d = {}
    try:
        import yaml
        d = yaml.safe_load(open(RULES_PATH, encoding="utf-8")) or {}
    except Exception as e:
        print(f"  ⚠️ 讀不到規則檔({e}),用內建預設。")
    t = d.get("target", {}) or {}
    s = d.get("significance", {}) or {}
    g = d.get("guardrails", {}) or {}
    m = d.get("market", {}) or {}
    return {
        "price": float(m.get("price_per_sale") or 39800),
        "cpa_target": float(t.get("cpa_target") or 13000),
        "cpa_keep_max": float(t.get("cpa_keep_max") or 16000),
        "cpl_ceiling": float(t.get("cpl_ceiling") or 150),
        "min_buyers": int(s.get("min_buyers_for_roas") or 3),
        "min_spend_verdict": float(s.get("min_spend_for_verdict") or 26000),
        "test_daily": 800.0,
        "cap_test_spend": 20000.0,
        "observe_floor": 3000.0,     # 花不到這、又還沒成交 → 觀察期,先不動
        "budget_step_pct": 25.0,
        "max_daily": float(t.get("max_daily_budget") or 5000),
        "max_pauses": int(g.get("max_pauses_per_run") or 10),
        # env DRY_RUN 若有設就蓋過 yaml(方便之後不改檔就上線);沒設則用 yaml(預設 true)
        "dry_run": (os.environ["DRY_RUN"].lower() != "false")
                   if os.environ.get("DRY_RUN") is not None else bool(g.get("dry_run", True)),
    }


def meta_campaigns(account):
    today = dt.date.today()
    since = (today - dt.timedelta(days=WINDOW)).isoformat()
    tr = {"since": since, "until": today.isoformat()}
    fields = ["id", "name", "status", "daily_budget", "effective_status"]
    camps = C.fb_retry(account.get_campaigns, fields=fields, params={"limit": 300})
    rows = []
    for c in camps:
        if c.get("effective_status") != "ACTIVE":
            continue
        spend, reg = 0.0, 0
        try:
            ins = C.fb_retry(c.get_insights, params={"time_range": tr},
                             fields=["spend", "actions"])
            if ins:
                r0 = ins[0]
                spend = float(r0.get("spend", 0) or 0)
                for a in (r0.get("actions") or []):
                    if _is_reg(a["action_type"]):
                        reg += int(float(a["value"]))
        except Exception as e:
            print(f"  ⚠️ insights 失敗 {c.get('name','')[:24]}: {e}")
        rows.append({
            "id": c["id"], "name": c.get("name", ""),
            "daily_budget": float(c.get("daily_budget", 0) or 0) / C.currency_offset(),
            "spend": spend, "reg": reg,
        })
    return rows


def buyers_by_campaign(window_since):
    buyers = read_buyers()
    win = [b for b in buyers if b.get("date") and b["date"] >= window_since]
    agg = defaultdict(int)
    for b in win:
        agg[norm(b.get("campaign") or "")] += 1
    return agg, len(win)


def match_buyers(camp_name, agg):
    key = norm(camp_name)
    if key in agg:
        return agg[key]
    n = 0
    for cn, cnt in agg.items():
        if cn and (cn in key or key in cn):
            n += cnt
    return n


def decide(r, T):
    sp, reg, bz = r["spend"], r["reg"], r["buyers"]
    cpl = sp / reg if reg else None
    cpa = sp / bz if bz else None
    roas = (bz * T["price"]) / sp if sp else None
    r["cpl"], r["cpa"], r["roas"] = cpl, cpa, roas

    # 有量(達顯著)：用 CPA/ROAS 判
    if bz >= T["min_buyers"]:
        if cpa <= T["cpa_target"]:
            return ("SCALE", f"CPA {cpa:.0f} ≤ {T['cpa_target']:.0f} · ROAS {roas:.1f} → +{T['budget_step_pct']:.0f}%")
        if cpa <= T["cpa_keep_max"]:
            return ("KEEP", f"CPA {cpa:.0f} · ROAS {roas:.1f}(保留線內)")
        return ("CUT", f"CPA {cpa:.0f} > {T['cpa_keep_max']:.0f} · ROAS {roas:.1f} → 減半/關")

    # 有 1–2 單(未達顯著)：給測試預算跑到顯著,或燒夠了就收
    if bz >= 1:
        if sp >= T["cap_test_spend"]:
            return ("PAUSE", f"測試已燒 {sp:.0f} 仍不足 {T['min_buyers']} 單")
        if cpl is None or cpl <= T["cpl_ceiling"]:
            return ("FUND", f"{bz} 單未達顯著 · 拉到 {T['test_daily']:.0f}/天測到夠量")
        return ("CUT", f"{bz} 單但 CPL {cpl:.0f} 過高")

    # 0 單
    if sp >= T["min_spend_verdict"]:
        return ("PAUSE", f"花 {sp:.0f}(≥2×CPA)仍 0 成交")
    if sp >= T["observe_floor"] and cpl and cpl > T["cpl_ceiling"]:
        return ("PAUSE", f"CPL {cpl:.0f} 爆表且 0 成交")
    if sp < T["observe_floor"]:
        return ("SKIP", f"觀察期(花 {sp:.0f} < {T['observe_floor']:.0f})")
    return ("KEEP", f"0 單 · 花 {sp:.0f} 觀察中")


def apply(r, action, T):
    camp = Campaign(r["id"])
    abo = r["daily_budget"] <= 0     # ABO：預算在 ad set,campaign 沒日預算
    if action == "PAUSE":
        C.fb_retry(camp.api_update, params={"status": "PAUSED"})
    elif action == "SCALE":
        if abo:
            print("       ↳ ABO：需在 ad set 加預算,自動略過")
            return
        nb = min(r["daily_budget"] * (1 + T["budget_step_pct"] / 100), T["max_daily"])
        C.fb_retry(camp.api_update, params={"daily_budget": C.to_minor(nb)})
    elif action == "FUND":
        if abo:
            print("       ↳ ABO：需在 ad set 調到測試預算,自動略過")
            return
        if r["daily_budget"] < T["test_daily"]:
            C.fb_retry(camp.api_update, params={"daily_budget": C.to_minor(T["test_daily"])})
    elif action == "CUT":
        if abo:
            C.fb_retry(camp.api_update, params={"status": "PAUSED"})
        else:
            C.fb_retry(camp.api_update, params={"daily_budget": C.to_minor(r["daily_budget"] / 2)})


def run():
    C.init_api()
    T = load_rules()
    account = AdAccount(C.ACT_ID)
    today = dt.date.today()
    since = today - dt.timedelta(days=WINDOW)
    rows = meta_campaigns(account)
    agg, win_buyers = buyers_by_campaign(since)
    for r in rows:
        r["buyers"] = match_buyers(r["name"], agg)

    print(f"[optimize · CPA-first] {C.AD_ACCOUNT_ID} | 視窗近 {WINDOW} 天({since}~{today}) | "
          f"{len(rows)} 支 ACTIVE | 目標CPA≤{T['cpa_target']:.0f} 保留≤{T['cpa_keep_max']:.0f} | DRY_RUN={T['dry_run']}")
    print(f"  視窗內買單 {win_buyers} 筆 · 客單價 NT${T['price']:.0f}")

    decided = [(r, *decide(r, T)) for r in rows]
    pauses = [1 for r, a, _ in decided if a in ("PAUSE",)]
    if len(pauses) > T["max_pauses"]:
        print(f"⚠️ 保護欄：要關 {len(pauses)} 支 (>{T['max_pauses']})，停手不執行，請人工檢查。")
        return

    print("  " + "-" * 96)
    print(f"  {'Campaign':30} | {'花費':>8} | {'報名':>5} | {'CPL':>5} | {'成交':>4} | {'CPA':>7} | {'ROAS':>5} | 動作")
    print("  " + "-" * 96)
    order = {"PAUSE": 0, "CUT": 1, "SCALE": 2, "FUND": 3, "KEEP": 4, "SKIP": 5}
    ts = tr_ = tb = 0.0
    for r, action, reason in sorted(decided, key=lambda x: (order.get(x[1], 9), -x[0]["spend"])):
        ts += r["spend"]; tr_ += r["reg"]; tb += r["buyers"]
        cpl = f"{r['cpl']:.0f}" if r.get("cpl") else "—"
        cpa = f"{r['cpa']:.0f}" if r.get("cpa") else "—"
        roas = f"{r['roas']:.2f}" if r.get("roas") else "—"
        print(f"  {r['name'][:30]:30} | {r['spend']:>8.0f} | {r['reg']:>5} | {cpl:>5} | "
              f"{r['buyers']:>4} | {cpa:>7} | {roas:>5} | {action} ({reason})")
        if not T["dry_run"] and action in ("PAUSE", "SCALE", "FUND", "CUT"):
            apply(r, action, T)
    print("  " + "-" * 96)
    avg_cpa = ts / tb if tb else 0
    print(f"  合計：花費 {ts:.0f} · 報名 {tr_:.0f} · 成交 {tb:.0f} · 平均CPA {avg_cpa:.0f} · "
          f"整體ROAS {(tb*T['price']/ts) if ts else 0:.2f}")
    print("完成。" + ("（dry run，未真的改）" if T["dry_run"] else " ⚡真跑，已執行動作"))


if __name__ == "__main__":
    run()
