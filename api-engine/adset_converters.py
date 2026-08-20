"""
Ad set 級鑽取：每個 campaign 底下,到底是『哪個 ad set』帶來成交?
用來精準重開——只開有轉化的 ad set,不整個 campaign 打開。

- 買單(Stripe)依 (campaign, ad set) 對:lifetime + 近 60 天。
- 拉全部 ad set 的目前狀態 + 歷史花費,配對起來。
- 依成交數排序,列出每個「有成交的 ad set」+ 現在是開/關 + ROAS。
只印彙總數字,無個資。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, GOOGLE_SA_JSON, PRICE_PER_SALE(選填)
"""
import os, datetime as dt
from collections import defaultdict
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from spend_audit import read_buyers, norm

PRICE = float(os.environ.get("PRICE_PER_SALE") or 39800)


def all_adsets(account):
    rows = C.fb_retry(account.get_ad_sets,
                      fields=["id", "name", "effective_status", "daily_budget", "campaign{id,name}"],
                      params={"limit": 500})
    out = {}
    for a in rows:
        camp = a.get("campaign") or {}
        cname = camp.get("name", "") if isinstance(camp, dict) else ""
        key = (norm(cname), norm(a.get("name", "")))
        out[key] = {"id": a["id"], "adset": a.get("name", ""), "camp": cname,
                    "eff": a.get("effective_status", ""),
                    "budget": float(a.get("daily_budget", 0) or 0) / C.currency_offset(),
                    "camp_id": camp.get("id") if isinstance(camp, dict) else None}
    return out


def spend_by_adset(account):
    out = defaultdict(float)
    try:
        rows = C.fb_retry(account.get_insights,
                          params={"level": "adset", "date_preset": "maximum", "limit": 500},
                          fields=["campaign_name", "adset_name", "spend"])
        for r in rows:
            out[(norm(r.get("campaign_name", "")), norm(r.get("adset_name", "")))] += float(r.get("spend", 0) or 0)
    except Exception as e:
        print(f"  ⚠️ insights 失敗: {e}")
    return out


def match(pair, amap):
    if pair in amap:
        return pair
    ck, ak = pair
    # 同 campaign 下 ad set 名稱包含匹配
    for (mc, ma) in amap:
        if mc == ck and ak and ma and (ak in ma or ma in ak):
            return (mc, ma)
    # campaign 也放寬
    for (mc, ma) in amap:
        if ck and mc and (ck in mc or mc in ck) and ak and ma and (ak in ma or ma in ak):
            return (mc, ma)
    return None


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    today = dt.date.today()
    since60 = today - dt.timedelta(days=60)

    buyers = read_buyers()
    life, w60 = defaultdict(int), defaultdict(int)
    for b in buyers:
        key = (norm(b.get("campaign") or ""), norm(b.get("adset") or ""))
        life[key] += 1
        if b.get("date") and b["date"] >= since60:
            w60[key] += 1

    amap = all_adsets(account)
    spend = spend_by_adset(account)

    rows = []
    for key, lb in life.items():
        mk = match(key, amap)
        if not mk:
            rows.append({"camp": key[0] or "?", "adset": key[1] or "(無)", "life": lb,
                         "w60": w60.get(key, 0), "eff": "(對不到/已刪?)", "spend": 0,
                         "budget": 0, "id": None, "camp_id": None, "roas": None})
            continue
        info = amap[mk]
        sp = spend.get(mk, 0)
        rows.append({"camp": info["camp"], "adset": info["adset"], "life": lb,
                     "w60": w60.get(key, 0), "eff": info["eff"], "spend": sp,
                     "budget": info["budget"], "id": info["id"], "camp_id": info["camp_id"],
                     "roas": (lb * PRICE / sp) if sp else None})

    rows.sort(key=lambda r: (-r["life"], -(r["roas"] or 0)))
    print("ADSET_CONVERTERS_START")
    print(f"{'狀態':12} {'成交(全/60)':>11} {'ROAS':>6} {'花費':>9} {'日預算':>7}  Campaign ▸ Ad set")
    for r in rows:
        act = "🟢開" if r["eff"] == "ACTIVE" else "🔴關"
        st = f"{act} {r['eff']}"
        roas = f"{r['roas']:.2f}" if r["roas"] else "—"
        camp = (r["camp"] or "")[:30]
        aset = (r["adset"] or "")[:34]
        print(f"{st:12} {str(r['life'])+'/'+str(r['w60']):>11} {roas:>6} {r['spend']:>9,.0f} "
              f"{r['budget']:>7,.0f}  {camp} ▸ {aset}")
    # 建議重開清單:目前關著、ROAS>=2.5、且近60天有成交
    print()
    print("== 🎯 建議重開的 ad set（現在關著 · ROAS≥2.5 · 近60天有成交）==")
    reopen = [r for r in rows if r["eff"] != "ACTIVE" and r["id"]
              and r["roas"] and r["roas"] >= 2.5 and r["w60"] >= 1]
    reopen.sort(key=lambda r: -(r["roas"] or 0))
    for r in reopen:
        print(f"  adset_id={r['id']}  camp_id={r['camp_id']}  ROAS {r['roas']:.2f}  "
              f"成交 {r['life']}/{r['w60']}  日預算 {r['budget']:,.0f}  | {r['camp'][:26]} ▸ {r['adset'][:30]}")
    if not reopen:
        print("  （無符合條件的）")
    print("ADSET_CONVERTERS_END")


if __name__ == "__main__":
    run()
