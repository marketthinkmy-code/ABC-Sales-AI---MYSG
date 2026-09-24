"""
CPL 為什麼變貴 —— 診斷。把「每個報名成本(CPL)」拆開看,分辨是:
  · 受眾疲乏(frequency 上升) · 素材疲乏(CTR 下降) · 競價變貴(CPM 上升) ·
  · 還是某條 campaign 花了錢卻幾乎沒報名(冷 pixel / 沒轉換)在拖高平均。

輸出:
  A. 帳號每週趨勢(近 ~90 天):花費 · CPM · CTR · 頻率 · 報名 · CPL —— 看它怎麼一路變貴。
  B. 目前 ACTIVE campaign(近 14 天):各自的 CPL · CPM · CTR · 頻率 —— 抓出兇手。
  C. 自動歸因:比對第一週 vs 最後一週,說是 CPM/CTR/頻率 哪個在推高 CPL。
只讀不改,不印個資。
env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, TREND_DAYS(預設 90), ACTIVE_DAYS(預設 14)
"""
import os
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from spend_audit import _is_reg

TREND_DAYS = int(os.environ.get("TREND_DAYS") or 90)
ACTIVE_DAYS = int(os.environ.get("ACTIVE_DAYS") or 14)


def _leads(row):
    n = 0
    for a in (row.get("actions") or []):
        if _is_reg(a["action_type"]):
            n += int(float(a["value"]))
    return n


def _f(row, k):
    try:
        return float(row.get(k, 0) or 0)
    except Exception:
        return 0.0


def account_trend(account):
    rows = C.fb_retry(account.get_insights, params={
        "date_preset": f"last_{TREND_DAYS}d" if TREND_DAYS in (30, 90) else "last_90d",
        "time_increment": "7"},
        fields=["date_start", "date_stop", "spend", "impressions", "reach",
                "frequency", "clicks", "ctr", "cpm", "actions"])
    out = []
    for r in rows:
        sp = _f(r, "spend")
        lead = _leads(r)
        out.append({
            "wk": r.get("date_start", "")[5:], "spend": sp, "cpm": _f(r, "cpm"),
            "ctr": _f(r, "ctr"), "freq": _f(r, "frequency"),
            "lead": lead, "cpl": (sp / lead) if lead else None,
        })
    return out


def active_campaigns(account):
    camps = C.fb_retry(account.get_campaigns,
                       fields=["id", "name", "effective_status"], params={"limit": 500})
    tr = {"date_preset": f"last_{ACTIVE_DAYS}d" if ACTIVE_DAYS in (7, 14, 30) else "last_14d"}
    rows = []
    for c in camps:
        try:
            ins = C.fb_retry(c.get_insights, params=tr,
                             fields=["spend", "impressions", "frequency", "ctr", "cpm", "actions"])
        except Exception:
            continue
        if not ins:
            continue
        r = ins[0]
        sp = _f(r, "spend")
        if sp <= 0:                      # 只看視窗內真的有花錢的
            continue
        lead = _leads(r)
        rows.append({"name": c.get("name", ""), "st": c.get("effective_status", ""),
                     "spend": sp, "lead": lead,
                     "cpl": (sp / lead) if lead else None,
                     "cpm": _f(r, "cpm"), "ctr": _f(r, "ctr"), "freq": _f(r, "frequency")})
    return sorted(rows, key=lambda x: -x["spend"])


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)

    print(f"========== CPL 診斷 · {C.AD_ACCOUNT_ID} ==========")
    tr = account_trend(account)
    print(f"\n[A. 帳號每週趨勢 · 近 {TREND_DAYS} 天]")
    print(f"  {'週起':>6} {'花費':>8} {'CPM':>6} {'CTR%':>5} {'頻率':>5} {'報名':>5} {'CPL':>6}")
    print("  " + "-" * 52)
    for w in tr:
        cpl = f"{w['cpl']:.0f}" if w["cpl"] else "—"
        print(f"  {w['wk']:>6} {w['spend']:>8.0f} {w['cpm']:>6.0f} {w['ctr']:>5.2f} "
              f"{w['freq']:>5.2f} {w['lead']:>5} {cpl:>6}")

    print(f"\n[B. 近 {ACTIVE_DAYS} 天有花錢的 campaign]（花費排序 · 抓 CPL 兇手）")
    ac = active_campaigns(account)
    print(f"  {'花費':>8} {'報名':>5} {'CPL':>6} {'CPM':>6} {'CTR%':>5} {'頻率':>5} {'狀態':<10} campaign")
    print("  " + "-" * 104)
    tsp = tld = 0.0
    for r in ac:
        cpl = f"{r['cpl']:.0f}" if r["cpl"] else "—"
        tsp += r["spend"]; tld += r["lead"]
        print(f"  {r['spend']:>8.0f} {r['lead']:>5} {cpl:>6} {r['cpm']:>6.0f} "
              f"{r['ctr']:>5.2f} {r['freq']:>5.2f} {r['st']:<10} {r['name'][:40]}")
    print("  " + "-" * 92)
    print(f"  ACTIVE 合計:花費 {tsp:.0f} · 報名 {tld:.0f} · 綜合 CPL "
          f"{(tsp/tld) if tld else 0:.0f} TWD")

    # C. 自動歸因:第一週 vs 最後一週
    good = [w for w in tr if w["lead"] and w["cpl"]]
    print("\n[C. 為什麼變貴 —— 第一週 vs 最後一週]")
    if len(good) >= 2:
        a, b = good[0], good[-1]
        def chg(x, y):
            return f"{((y-x)/x*100):+.0f}%" if x else "—"
        print(f"  CPL : {a['cpl']:.0f} → {b['cpl']:.0f}  ({chg(a['cpl'], b['cpl'])})")
        print(f"  CPM : {a['cpm']:.0f} → {b['cpm']:.0f}  ({chg(a['cpm'], b['cpm'])})  ← 競價/版位變貴")
        print(f"  CTR : {a['ctr']:.2f} → {b['ctr']:.2f}  ({chg(a['ctr'], b['ctr'])})  ← 掉=素材疲乏")
        print(f"  頻率: {a['freq']:.2f} → {b['freq']:.2f}  ({chg(a['freq'], b['freq'])})  ← 升=受眾看膩")
        # 粗略拆解:CPL ≈ CPM /(CTR/100)/(每點擊轉換率)
        cpc_a = a["cpm"] / (a["ctr"] * 10) if a["ctr"] else None   # CPM/(CTR%*1000/100)
        cpc_b = b["cpm"] / (b["ctr"] * 10) if b["ctr"] else None
        if cpc_a and cpc_b:
            print(f"  每點擊成本(推算 CPC): {cpc_a:.1f} → {cpc_b:.1f}  ({chg(cpc_a, cpc_b)})")
        drivers = []
        if b["cpm"] > a["cpm"] * 1.15:
            drivers.append("CPM 上升(競價/版位變貴)")
        if b["ctr"] < a["ctr"] * 0.85:
            drivers.append("CTR 下降(素材疲乏)")
        if b["freq"] > a["freq"] * 1.15:
            drivers.append("頻率上升(受眾看膩/太窄)")
        print(f"  → 主要推手:{('、'.join(drivers)) if drivers else '皆非單一因素,看 B 表是否某條 campaign 花錢沒報名在拖'}")
    else:
        print("  週資料不足或報名太少,無法自動比對(看 B 表:是否有 campaign 花錢卻 0 報名)。")
    print("========== END ==========")


if __name__ == "__main__":
    run()
