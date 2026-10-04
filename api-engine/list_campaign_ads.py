"""
只讀:列出指定 campaign 的 ad set + 廣告的『名稱與狀態』,用來確認哪些影片已做成廣告、
在 Ads Manager 叫什麼名字、是 PAUSED 還是 ACTIVE。不印任何個資。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID,
     LIST_CAMPAIGN_IDS(逗號分隔;預設=興趣測試T1,完整片測試T1)
"""
import os
import config as C
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet

IDS = [s.strip() for s in (os.environ.get("LIST_CAMPAIGN_IDS")
       or "120247254989860658,120247263797180658").split(",") if s.strip()]


def run():
    C.init_api()
    print("LIST_START")
    for cid in IDS:
        try:
            c = C.fb_retry(lambda: Campaign(cid).api_get(fields=["name", "effective_status"]))
        except Exception as e:
            print(f"\n[campaign {cid}] 讀取失敗: {str(e)[:100]}")
            continue
        print(f"\n══════ campaign {cid}｜{c.get('name','')}｜{c.get('effective_status')} ══════")
        adsets = C.fb_retry(lambda: list(Campaign(cid).get_ad_sets(
            fields=["name", "effective_status"], params={"limit": 100})))
        adsets = sorted(adsets, key=lambda a: a["id"])
        n_ad = 0
        for a in adsets:
            ads = C.fb_retry(lambda: list(AdSet(a["id"]).get_ads(
                fields=["name", "effective_status"], params={"limit": 50})))
            tag = "（空）" if not ads else ""
            print(f"  ▸ ad set｜{a.get('name','')}｜{a.get('effective_status')}{tag}")
            for ad in ads:
                n_ad += 1
                print(f"      · {ad.get('name','')}｜{ad.get('effective_status')}")
        print(f"  = {len(adsets)} 個 ad set · {n_ad} 支廣告")
    print("\nLIST_END")


if __name__ == "__main__":
    run()
