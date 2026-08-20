"""
成交來源 × campaign 開/關 對照：
  我最近的成交,是來自『還開著的 campaign』,還是來自『我已經關掉的 campaign』?

- 買單(Stripe Sheet)依 campaign(UTM source)彙總:lifetime + 近 60 天。
- 拉『全部』campaign(含 PAUSED/ARCHIVED)的目前狀態 + 歷史花費。
- 對起來分四類:
    🟢 開著·有成交   🔴 已關·有成交(=你關掉的轉化來源)
    🟡 開著·0成交(新內容/沒轉化)   ⚪ 對不到現有campaign(可能已刪)
只印彙總數字,無個資。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, GOOGLE_SA_JSON, PRICE_PER_SALE(選填)
"""
import os, datetime as dt
from collections import defaultdict
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from spend_audit import read_buyers, norm

PRICE = float(os.environ.get("PRICE_PER_SALE") or 39800)


def all_campaigns(account):
    rows = C.fb_retry(account.get_campaigns,
                      fields=["id", "name", "effective_status", "status"],
                      params={"limit": 500})
    out = {}
    for c in rows:
        out[norm(c.get("name", ""))] = {
            "name": c.get("name", ""),
            "eff": c.get("effective_status", ""),
        }
    return out


def spend_by_campaign(account, preset):
    out = defaultdict(float)
    try:
        rows = C.fb_retry(account.get_insights, params={"level": "campaign", "date_preset": preset, "limit": 500},
                          fields=["campaign_name", "spend"])
        for r in rows:
            out[norm(r.get("campaign_name", ""))] += float(r.get("spend", 0) or 0)
    except Exception as e:
        print(f"  ⚠️ insights({preset}) 失敗: {e}")
    return out


def is_active(eff):
    return eff == "ACTIVE"


def match(campkey, camp_map):
    if campkey in camp_map:
        return campkey
    for k in camp_map:
        if k and campkey and (k in campkey or campkey in k):
            return k
    return None


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    today = dt.date.today()
    since60 = today - dt.timedelta(days=60)

    buyers = read_buyers()
    life_b, w60_b = defaultdict(int), defaultdict(int)
    for b in buyers:
        ck = norm(b.get("campaign") or "")
        life_b[ck] += 1
        if b.get("date") and b["date"] >= since60:
            w60_b[ck] += 1

    camp_map = all_campaigns(account)
    sp_life = spend_by_campaign(account, "maximum")

    # 把每個「有買單的 campaign」對到現有 campaign 狀態
    groups = {"active_conv": [], "paused_conv": [], "active_noconv": [], "unmatched_conv": []}
    seen = set()
    for ck, life in sorted(life_b.items(), key=lambda x: -x[1]):
        mk = match(ck, camp_map) if ck else None
        name = camp_map[mk]["name"] if mk else (ck or "(空白/無 UTM)")
        eff = camp_map[mk]["eff"] if mk else None
        spend = sp_life.get(mk, 0) if mk else 0
        rec = {"name": name, "life": life, "w60": w60_b.get(ck, 0), "spend": spend, "eff": eff}
        if mk:
            seen.add(mk)
        if mk and is_active(eff):
            groups["active_conv"].append(rec)
        elif mk and not is_active(eff):
            groups["paused_conv"].append(rec)
        else:
            groups["unmatched_conv"].append(rec)

    # 開著但 0 成交(新內容/沒轉化)
    for mk, info in camp_map.items():
        if is_active(info["eff"]) and mk not in seen:
            groups["active_noconv"].append({"name": info["name"], "life": 0, "w60": 0,
                                            "spend": sp_life.get(mk, 0), "eff": info["eff"]})

    life_total = sum(life_b.values())
    w60_total = sum(w60_b.values())
    life_active = sum(r["life"] for r in groups["active_conv"])
    life_paused = sum(r["life"] for r in groups["paused_conv"])
    life_unm = sum(r["life"] for r in groups["unmatched_conv"])
    w60_active = sum(r["w60"] for r in groups["active_conv"])
    w60_paused = sum(r["w60"] for r in groups["paused_conv"])

    def pct(a, b):
        return f"{a/b*100:.0f}%" if b else "—"

    print("STATUS_AUDIT_START")
    print(f"買單 lifetime {life_total} 筆 · 近60天 {w60_total} 筆")
    print(f"lifetime 成交來源：🟢開著 {life_active}（{pct(life_active,life_total)}） · "
          f"🔴已關 {life_paused}（{pct(life_paused,life_total)}） · ⚪對不到 {life_unm}（{pct(life_unm,life_total)}）")
    print(f"近60天 成交來源：🟢開著 {w60_active}（{pct(w60_active,w60_total)}） · "
          f"🔴已關 {w60_paused}（{pct(w60_paused,w60_total)}）")
    print()

    def dump(title, key, show_status=False):
        rows = sorted(groups[key], key=lambda x: -x["life"])
        print(f"== {title}（{len(rows)} 支）==")
        for r in rows:
            st = f" [{r['eff']}]" if show_status and r["eff"] else ""
            roas = (r["life"] * PRICE / r["spend"]) if r["spend"] else None
            sp = f"花費 {r['spend']:,.0f}" if r["spend"] else "花費 —"
            ro = f" · ROAS {roas:.2f}" if roas else ""
            print(f"  {(r['name'] or '')[:44]:46s}{st}  成交 lifetime {r['life']} / 近60天 {r['w60']} · {sp}{ro}")
        if not rows:
            print("  （無）")
        print()

    dump("🔴 已關掉、但曾經有成交 —— 你關掉的轉化來源", "paused_conv", show_status=True)
    dump("🟢 還開著、且有成交 —— 老內容確實在轉化", "active_conv")
    dump("🟡 還開著、但 0 成交 —— 新內容/沒轉化(觀察或砍)", "active_noconv")
    dump("⚪ 對不到現有 campaign（可能已刪除）、但有成交", "unmatched_conv")
    print("STATUS_AUDIT_END")


if __name__ == "__main__":
    run()
