"""
只讀探勘,給『贏家放大 + 興趣定向新 ad set』鋪路:
  A. 找出贏家廣告 → 它們所在 ad set / campaign / 日預算 / 狀態 / 近 14 天 花費·報名·CPL。
  B. 依 ICP 種子字,查 Meta 興趣(adinterest)→ id·名稱·受眾量·分類,好挑來建興趣 ad set。

只讀不改。不印任何個資。
env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, WINNER_KWS(選填,逗號分隔), SINCE(選填)
"""
import os, re, datetime as dt
import config as C
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet
from spend_audit import _is_reg

WINNER_KWS = [s.strip() for s in (os.environ.get("WINNER_KWS")
              or "M1Video 9,M1Video 8,M1Video 1,WINNERS ROAS3+").split(",") if s.strip()]
SINCE = os.environ.get("SINCE") or (dt.date.today() - dt.timedelta(days=14)).isoformat()
UNTIL = dt.date.today().isoformat()
OFF = C.currency_offset()

ICP_SEEDS = [s.strip() for s in (os.environ.get("ICP_SEEDS") or
    "創業,中小企業,電子商務,網路行銷,數位行銷,銷售,企業家,顧問,線上課程,"
    "美容,餐飲,門市,蝦皮,小型企業主,Shopify,行銷").split(",") if s.strip()]


def _match(nm):
    for w in WINNER_KWS:
        if w and w[-1].isdigit():
            if re.search(re.escape(w) + r"(?!\d)", nm):
                return w
        elif w in nm:
            return w
    return None


def adset_insight(aset_id):
    tr = {"since": SINCE, "until": UNTIL}
    spend, reg = 0.0, 0
    try:
        ins = C.fb_retry(AdSet(aset_id).get_insights, params={"time_range": tr},
                         fields=["spend", "actions"])
        if ins:
            spend = float(ins[0].get("spend", 0) or 0)
            for a in (ins[0].get("actions") or []):
                if _is_reg(a["action_type"]):
                    reg += int(float(a["value"]))
    except Exception as e:
        print(f"      ⚠️ insights {aset_id}: {str(e)[:60]}")
    return spend, reg


def winners(account):
    print(f"[A] 贏家廣告(名稱含 {WINNER_KWS})· 近 14 天({SINCE}~{UNTIL})")
    ads = list(C.fb_retry(account.get_ads,
                          fields=["name", "adset_id", "effective_status", "creative"],
                          params={"limit": 1000}))
    by_adset = {}
    for ad in ads:
        kw = _match(ad.get("name", ""))
        if not kw:
            continue
        aid = ad.get("adset_id")
        by_adset.setdefault(aid, {"kws": set(), "n": 0})
        by_adset[aid]["kws"].add(kw)
        by_adset[aid]["n"] += 1
    print(f"  命中 {sum(v['n'] for v in by_adset.values())} 支廣告,分布在 {len(by_adset)} 個 ad set")
    print("  " + "-" * 104)
    print(f"  {'adset_id':<20} {'狀態':<10} {'日預算':>7} {'花費14d':>8} {'報名':>4} {'CPL':>7} 廣告數 | campaign")
    print("  " + "-" * 104)
    for aid, v in by_adset.items():
        try:
            a = C.fb_retry(AdSet(aid).api_get,
                           fields=["name", "effective_status", "daily_budget", "campaign{name}"])
        except Exception as e:
            print(f"  {aid} 讀取失敗 {str(e)[:50]}")
            continue
        db = float(a.get("daily_budget", 0) or 0) / OFF
        camp = a.get("campaign") or {}
        cname = camp.get("name", "") if isinstance(camp, dict) else ""
        sp, reg = adset_insight(aid)
        cpl = sp / reg if reg else None
        cpls = f"{cpl:.0f}" if cpl else "—"
        print(f"  {aid:<20} {a.get('effective_status',''):<10} {db:>7.0f} {sp:>8.0f} {reg:>4} "
              f"{cpls:>7} {v['n']:>5} | {cname[:34]}")


def interests(account):
    api = FacebookAdsApi.get_default_api()
    print(f"\n[B] ICP 興趣搜尋(adinterest)· 種子 {len(ICP_SEEDS)} 個")
    print("  " + "-" * 96)
    print(f"  {'interest_id':<18} {'受眾量下限':>10} {'名稱 / 分類':<40} 種子")
    print("  " + "-" * 96)
    seen = set()
    for seed in ICP_SEEDS:
        try:
            resp = api.call("GET", ("search",),
                            params={"type": "adinterest", "q": seed, "limit": 6,
                                    "locale": "zh_TW"})
            data = (resp.json() or {}).get("data", [])
        except Exception as e:
            print(f"  種子「{seed}」搜尋失敗: {str(e)[:60]}")
            continue
        for it in data:
            iid = it.get("id")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            lo = it.get("audience_size_lower_bound") or it.get("audience_size") or 0
            topic = it.get("topic") or ""
            nm = it.get("name", "")
            print(f"  {iid:<18} {int(lo):>10,} {(nm+' · '+topic)[:40]:<40} {seed}")
    print(f"  → 共 {len(seen)} 個不重複興趣。挑受眾量夠大又貼 ICP 的來建興趣 ad set。")


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    winners(account)
    interests(account)


if __name__ == "__main__":
    run()
