"""
把指定 campaign(可多個,逗號分隔)整條開 ACTIVE:所有 ad → 所有 ad set → campaign。
只動「沒被 DISAPPROVED 等問題擋住」的 ad(跳過不能開的)。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, ACTIVATE_CAMPAIGNS, DRY_RUN(預設 true)
用法: DRY_RUN=false ACTIVATE_CAMPAIGNS=123,456 python activate_campaign.py
"""
import os
import config as C
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad

CAMPS = [s.strip() for s in (os.environ.get("ACTIVATE_CAMPAIGNS") or "").split(",") if s.strip()]
# 這些狀態代表「沒過審/不能開」,不要嘗試開
SKIP_AD = {"DISAPPROVED", "WITH_ISSUES", "PENDING_REVIEW", "PENDING_BILLING_INFO"}


def run():
    if not CAMPS:
        raise SystemExit("沒給 ACTIVATE_CAMPAIGNS。")
    C.init_api()
    for camp in CAMPS:
        name = C.fb_retry(lambda: Campaign(camp).api_get(fields=["name"]).get("name")) or camp
        adsets = C.fb_retry(lambda: list(Campaign(camp).get_ad_sets(fields=["id", "name"], params={"limit": 200})))
        print(f"[activate] campaign {camp}: {name} | {len(adsets)} 個 ad set | DRY_RUN={C.DRY_RUN}")
        for s in adsets:
            ads = C.fb_retry(lambda: list(AdSet(s["id"]).get_ads(fields=["id", "name", "effective_status"], params={"limit": 200})))
            on = [a for a in ads if a.get("effective_status") not in SKIP_AD]
            skip = [a for a in ads if a.get("effective_status") in SKIP_AD]
            print(f"  ── ad set {s['id']}（{s.get('name','')[:40]}）: 開 {len(on)} 支, 跳過 {len(skip)} 支")
            for a in skip:
                print(f"       ⏭ {a.get('effective_status')}  {a.get('name','')[:40]}")
            if C.DRY_RUN:
                continue
            for a in on:
                try:
                    C.fb_retry(Ad(a["id"]).api_update, params={"status": "ACTIVE"})
                except Exception as e:
                    print(f"       ⚠️ ad {a['id']} 開啟失敗: {str(e)[:80]}")
            try:
                C.fb_retry(AdSet(s["id"]).api_update, params={"status": "ACTIVE"})
            except Exception as e:
                print(f"     ⚠️ ad set {s['id']} 開啟失敗: {str(e)[:80]}")
        if not C.DRY_RUN:
            C.fb_retry(Campaign(camp).api_update, params={"status": "ACTIVE"})
            print(f"  ✅ campaign {camp} + ad set + 廣告 已開 ACTIVE。")
        else:
            print("  (DRY:未開。DRY_RUN=false 才真的開。)")


if __name__ == "__main__":
    run()
