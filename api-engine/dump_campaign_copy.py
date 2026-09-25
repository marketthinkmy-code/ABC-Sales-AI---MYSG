"""
把某條 campaign 底下每支廣告的『真實文案』(primary_text / headline)整段 dump 出來。
預設 = 興趣測試 T1(120247254989860658),用來把 8 支 hook 的文案交回給 WK。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, DUMP_CAMPAIGN_ID(預設興趣測試 T1)
用法: python dump_campaign_copy.py
"""
import os
import config as C
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adcreative import AdCreative

CAMP_ID = os.environ.get("DUMP_CAMPAIGN_ID") or "120247254989860658"


def _body_title(creative_id):
    cr = AdCreative(creative_id).api_get(
        fields=["body", "title", "object_story_spec", "asset_feed_spec"])
    body = cr.get("body") or ""
    title = cr.get("title") or ""
    oss = cr.get("object_story_spec") or {}
    for key in ("link_data", "video_data"):
        d = oss.get(key) or {}
        body = body or d.get("message", "")
        title = title or d.get("title", "") or d.get("name", "")
    afs = cr.get("asset_feed_spec") or {}
    if not body and afs.get("bodies"):
        body = afs["bodies"][0].get("text", "")
    if not title and afs.get("titles"):
        title = afs["titles"][0].get("text", "")
    return body, title


def run():
    C.init_api()
    adsets = C.fb_retry(lambda: list(
        Campaign(CAMP_ID).get_ad_sets(fields=["id", "name"], params={"limit": 100})))
    adsets = sorted(adsets, key=lambda a: a["id"])
    print("CAMPAIGN_COPY_DUMP_START")
    print(f"campaign {CAMP_ID} · {len(adsets)} 支 ad set\n")
    for a in adsets:
        ads = C.fb_retry(lambda: list(AdSet(a["id"]).get_ads(
            fields=["name", "creative"], params={"limit": 50})))
        for ad in ads:
            cr = ad.get("creative") or {}
            cid = cr.get("id") if isinstance(cr, dict) else None
            body, title = ("", "")
            if cid:
                try:
                    body, title = _body_title(cid)
                except Exception as e:
                    body = f"(讀取失敗: {e})"
            print(f"\n══════ [{a.get('name','')}] {ad.get('name','')} ══════")
            print(f"[標題] {title}")
            print(f"[文案 {len(body)}字]\n{body}")
    print("\nCAMPAIGN_COPY_DUMP_END")


if __name__ == "__main__":
    run()
