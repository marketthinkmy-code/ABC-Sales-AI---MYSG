"""
開一個新的『贏家放大』Campaign(CBO)，只放 ROAS >= 門檻的贏家素材。
不動任何現有 campaign。全部 PAUSED,人工檢查後才開。

- 從 reports/cpa_data.json 讀 ROAS>=ROAS_MIN 的素材 → 依名稱在帳號找到現有廣告 → 取 creative_id
- 建 CBO campaign(日預算 BUDGET) → clone 合規 ad set(繼承台灣廣告主聲明) → 設 Broad(Advantage+)
- 把贏家用『引用現有 creative_id』的方式放進去(不建新貼文)

用法: python launch_winners.py
env: META_ACCESS_TOKEN, AD_ACCOUNT_ID
"""
import os, json, re
import config as C
import launch as L
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet

ROAS_MIN = float(os.environ.get("WINNER_ROAS_MIN") or 3.0)
BUDGET = float(os.environ.get("WINNER_BUDGET") or 2000)   # TWD/日, CBO
NAME = os.environ.get("WINNER_CAMPAIGN_NAME") or "AI獲客-自動 | WINNERS ROAS3+"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "reports", "cpa_data.json")


def winner_keywords():
    d = json.load(open(DATA, encoding="utf-8"))
    kws = []
    for r in d["lifetime"]:
        if (r.get("roas") or 0) < ROAS_MIN:
            continue
        nm = r["name"]
        if "Ad_TW_" in nm:
            m = re.search(r"Ad_TW_[A-Za-z0-9_]+", nm)
            kw = m.group(0) if m else nm
        else:                                   # 影片:取到全形冒號前
            kw = nm.split("：")[0].strip()
        kws.append((kw, r.get("roas")))
    return kws


def make_cbo_campaign(account, name):
    return account.create_campaign(params={
        "name": name, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "daily_budget": C.to_minor(BUDGET),
    })["id"]


def set_broad(adset_id):
    tmpl = C.load_yaml("launch_template.yaml")["ad_set"]
    AdSet(adset_id).api_update(params={"targeting": {
        "geo_locations": {"countries": tmpl["geo"]["countries"]},
        "age_min": tmpl.get("age_min", 25), "age_max": tmpl.get("age_max", 55),
        "targeting_automation": {"advantage_audience": 1},
    }})


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    kws = winner_keywords()
    if not kws:
        raise SystemExit(f"cpa_data.json 裡沒有 ROAS>={ROAS_MIN} 的素材,先跑 weekly_cpa。")
    print(f"[winners] ROAS>={ROAS_MIN} 共 {len(kws)} 支:")
    for kw, roas in kws:
        print(f"    ROAS {roas:.2f}  {kw}")

    winners = L.find_winner_ads(account, [k for k, _ in kws])
    if not winners:
        raise SystemExit("在帳號找不到這些贏家廣告(可能已刪),無法引用 creative。")
    print(f"  找到 {len(winners)}/{len(kws)} 支現有贏家廣告可引用")

    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, NAME)
    camp = make_cbo_campaign(account, NAME)
    print(f"  ✓ CBO campaign {camp}（日預算 {BUDGET:.0f} TWD）")
    # 用第一支贏家自己的合規 ad set 當 clone 來源,確保台灣廣告主聲明繼承
    src_adset = winners[0]["adset_id"] or C.CLONE_SOURCE_ADSET
    adset = L.clone_compliant_adset(account, camp, f"{NAME} | Broad", src_adset)
    try:
        set_broad(adset)
        print(f"  ✓ Broad ad set {adset}（TW / Advantage+）")
    except Exception as e:
        print(f"  ⚠️ 設 Broad 目標失敗(沿用來源受眾): {e}")
    n = L.copy_winner_ads(account, adset, winners, NAME)
    print(f"→ 已建 {n} 支贏家廣告(PAUSED) 於新 CBO campaign。檢查無誤後開 ACTIVE。")


if __name__ == "__main__":
    run()
