"""
把指定 campaign(預設:今天的影片 campaign)整個開 ACTIVE。
campaign / 底下所有 ad set / 所有 ad 都設成 ACTIVE。全程用 fb_retry 扛帳號速率限制。

用法:
  python activate.py                       # 開 N.campaign_name("Video") 那個
  python activate.py --match "AI獲客 · Video"  # 用名稱關鍵字比對
env: META_ACCESS_TOKEN, AD_ACCOUNT_ID
"""
import os, argparse
import config as C
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad


def find_campaigns(account, match):
    camps = C.fb_retry(lambda: list(account.get_campaigns(
        fields=["id", "name", "effective_status"], params={"limit": 200})))
    return [c for c in camps if match in (c.get("name") or "")]


def activate(obj_cls, oid):
    C.fb_retry(obj_cls(oid).api_update, params={"status": "ACTIVE"})


def run(match):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    targets = find_campaigns(account, match)
    if not targets:
        raise SystemExit(f"找不到名稱含「{match}」的 campaign。")
    for c in targets:
        cid, cname = c["id"], c.get("name")
        print(f"▶ 開啟 campaign {cid}｜{cname}")
        adsets = C.fb_retry(lambda: list(Campaign(cid).get_ad_sets(fields=["id", "name"])))
        n_ad = 0
        for a in adsets:
            ads = C.fb_retry(lambda: list(AdSet(a["id"]).get_ads(fields=["id", "name"])))
            for ad in ads:
                try:
                    activate(Ad, ad["id"])
                    n_ad += 1
                    print(f"    ✓ ad ACTIVE｜{ad.get('name')}")
                except Exception as e:
                    print(f"    ⚠️ ad {ad['id']} 開啟失敗: {e}")
            try:
                activate(AdSet, a["id"])
                print(f"  ✓ ad set ACTIVE｜{a.get('name')}")
            except Exception as e:
                print(f"  ⚠️ ad set {a['id']} 開啟失敗: {e}")
        # 最後才開 campaign,確保底下都就緒
        activate(Campaign, cid)
        print(f"✅ campaign ACTIVE，共開 {len(adsets)} 個 ad set / {n_ad} 支廣告。")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--match", default=N.campaign_name("Video"),
                   help="用名稱關鍵字比對要開的 campaign")
    run(p.parse_args().match)
