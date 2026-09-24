"""
興趣測試 campaign — 一個新的 ABO campaign，底下每個興趣各開一支 ad set，
方便之後往裡面「大量塞新廣告」測試，並且靠單一興趣賽馬看哪個受眾成交。

合規做法(沿用 launch.py 已驗證路線):
  不從零建 ad set(會踩台灣廣告主聲明的坑)，而是「複製一個已合規的 ad set」
  (CLONE_SOURCE_ADSET，自動繼承台灣 advertiser / regional_regulated_categories),
  複製後只覆蓋 targeting → 保留原本的人口/版位設定(= 你「之前的那個模樣」),
  疊加單一興趣 flexible_spec + advantage_audience=0(讓興趣真的生效)。
  舊廣告刪掉，換上贏家素材(引用 creative_id，不建新貼文)。

全部 PAUSED。DRY_RUN=true 只印計畫不動帳號。

用法:
  DRY_RUN=true  python launch_interest_test.py --round T1
  DRY_RUN=false python launch_interest_test.py --round T1   # 真的建(仍 PAUSED)
"""
import argparse
import config as C
import launch as L
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.ad import Ad


# --- 我幫你想的興趣受眾(ICP：老闆/自雇、軟體使用度高、靠 LINE/IG/FB DM 成交) -----
# 每個興趣 = 一支獨立 ad set，單一興趣才看得出誰成交。id 是 Meta 興趣 id;
# 想改就改這份清單(或用 INTEREST_JSON 環境變數整包覆蓋)。
INTERESTS = [
    {"label": "中小企業主",   "ids": ["6003136069408"]},   # Small business
    {"label": "企業家精神",   "ids": ["6003371567474"]},   # Entrepreneurship
    {"label": "電子商務",     "ids": ["6003221485467"]},   # E-commerce
    {"label": "Shopify賣家",  "ids": ["6003230166788"]},   # Shopify
    {"label": "數位行銷",     "ids": ["6003127206524"]},   # Digital marketing
    {"label": "社群媒體行銷", "ids": ["6003389760112"]},   # Social media marketing
    {"label": "美業/美容",    "ids": ["6003088846792"]},   # Beauty salons
    {"label": "新創公司",     "ids": ["6003325004380"]},   # Startups
]


def _load_interests():
    import json
    raw = C._get("INTEREST_JSON")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            print(f"  (INTEREST_JSON 解析失敗，用內建清單: {e})")
    return INTERESTS


def _adset_budget():
    # 測試 campaign：每支興趣 ad set 的日預算(TWD)。預設 300。
    return float(C._get("INTEREST_ADSET_BUDGET", "300"))


def clone_interest_adset(account, campaign_id, name, interest):
    """複製已合規 ad set 到新 campaign，覆蓋 targeting 疊加單一興趣，回傳新 ad set id。
    保留來源的人口/版位/地區(= 之前的模樣)，只加興趣層。"""
    src_id = C.CLONE_SOURCE_ADSET
    resp = AdSet(src_id).create_copy(params={
        "campaign_id": campaign_id, "status_option": "PAUSED"})
    new_id = (resp.get("copied_adset_id") or resp.get("id")
              or (resp.get("ad_object_ids") or {}).get("adset")) if hasattr(resp, "get") else None
    if not new_id:
        new_id = resp["copied_adset_id"]
    aset = AdSet(new_id)

    # 讀回複製過來的 targeting，只疊加興趣層 + 關掉 Advantage+ 受眾(否則興趣不綁)。
    cur = AdSet(new_id).api_get(fields=["targeting"]).get("targeting") or {}
    tgt = dict(cur)
    tgt["flexible_spec"] = [{"interests": [{"id": i} for i in interest["ids"]]}]
    ta = dict(tgt.get("targeting_automation") or {})
    ta["advantage_audience"] = 0
    tgt["targeting_automation"] = ta

    aset.api_update(params={"name": name, "status": "PAUSED", "targeting": tgt})
    # ABO：ad set 設日預算(來源若是 CBO 會失敗 → 略過沿用來源)
    try:
        aset.api_update(params={"daily_budget": C.to_minor(_adset_budget())})
    except Exception as e:
        print(f"    (設 ad set 預算略過: {e})")
    # 刪掉複製來的舊廣告，換上我們的素材
    for ad in aset.get_ads(fields=["id"]):
        try:
            Ad(ad["id"]).api_delete()
        except Exception:
            pass
    return new_id


def run(round_tag):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    interests = _load_interests()
    tmpl = C.load_yaml("launch_template.yaml")
    brand = tmpl["brand"]["code"]
    camp_name = f"{brand} | 興趣測試 | {round_tag}"
    budget = _adset_budget()

    print(f"[interest-test] 帳號 {C.AD_ACCOUNT_ID} | {len(interests)} 個興趣 ad set "
          f"| 每支 {budget:.0f} TWD/日 | DRY_RUN={C.DRY_RUN}")
    print(f"  campaign: {camp_name} (ABO / OUTCOME_SALES / PAUSED)")
    for it in interests:
        print(f"    · {it['label']}  interests={it['ids']}")

    if C.DRY_RUN:
        print("  [dry] 以上為計畫。設 DRY_RUN=false 才會真的建(仍 PAUSED)。")
        return

    missing = [k for k, v in {"PAGE_ID": C.PAGE_ID, "PIXEL_ID": C.PIXEL_ID,
                              "LANDING_URL": C.LANDING_URL,
                              "CLONE_SOURCE_ADSET": C.CLONE_SOURCE_ADSET}.items() if not v]
    if missing:
        raise SystemExit(f"缺少必填: {', '.join(missing)}")

    L.ensure_page_advertiser()
    # 先找贏家素材(引用 creative_id)當每支 ad set 的種子廣告
    winners = L.find_winner_ads(account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到贏家廣告(關鍵字對不上)，請檢查 WINNER_AD_KEYWORDS。")

    L.delete_existing_campaigns(account, camp_name)
    camp_id = account.create_campaign(params={
        "name": camp_name,
        "objective": C.OBJECTIVE,
        "special_ad_categories": [],
        "status": "PAUSED",
        "is_adset_budget_sharing_enabled": False,   # ABO
    })["id"]
    print(f"  ✓ campaign {camp_id}")

    try:
        for it in interests:
            aset_name = f"{camp_name} | {it['label']}"
            aset_id = clone_interest_adset(account, camp_id, aset_name, it)
            n = L.copy_winner_ads(account, aset_id, winners, aset_name)
            print(f"  ✓ [{it['label']}] ad set {aset_id} ← {n} 支贏家素材")
    except Exception:
        try:
            Campaign(camp_id).api_delete()
            print(f"  (失敗，已刪半成品 campaign {camp_id})")
        except Exception:
            pass
        raise

    print(f"  → 完成。campaign {camp_id} 全 PAUSED；之後把新測試廣告直接塞進這些 ad set。")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--round", default="T1", help="本輪標記，如 T1")
    args = p.parse_args()
    run(args.round)
