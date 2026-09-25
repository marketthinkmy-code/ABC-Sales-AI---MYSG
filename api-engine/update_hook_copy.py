"""
把「興趣測試」campaign 那 8 支 hook 廣告的文案,換成 config/hook_copy_v2.json 的短句版。
影片、版位、預算、PAUSED 狀態全部不動——只換 creative(新文案)。

做法:每支廣告讀出它現在的 video_id → 依 video_id 對到新文案 → 建一個新的 creative
(同影片 + 新文案/標題)→ 把廣告指到新 creative。舊 creative 留著不影響。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, INSTAGRAM_ID …
     UPDATE_CAMPAIGN_ID(預設興趣測試 T1), DRY_RUN(預設 true)
用法: DRY_RUN=false python update_hook_copy.py
"""
import os, json
import config as C
import video_pipeline as VP
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.adaccount import AdAccount

CAMP_ID = os.environ.get("UPDATE_CAMPAIGN_ID") or "120247254989860658"
DATA = os.path.join(C.ROOT, "config", "hook_copy_v2.json")


def _creative_id(ad):
    cr = ad.get("creative") or {}
    if not cr:
        return None
    try:
        return cr["id"]
    except Exception:
        return cr.get("id") if hasattr(cr, "get") else None


def _video_id(creative_id):
    oss = AdCreative(creative_id).api_get(fields=["object_story_spec"]).get("object_story_spec") or {}
    vd = oss.get("video_data") or {}
    return vd.get("video_id")


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    copy = json.load(open(DATA, encoding="utf-8"))
    adsets = C.fb_retry(lambda: list(
        Campaign(CAMP_ID).get_ad_sets(fields=["id", "name"], params={"limit": 100})))
    adsets = sorted(adsets, key=lambda a: a["id"])
    print(f"[update-copy] campaign {CAMP_ID} · {len(adsets)} 支 ad set · DRY_RUN={C.DRY_RUN}")

    n = 0
    for a in adsets:
        ads = C.fb_retry(lambda: list(AdSet(a["id"]).get_ads(
            fields=["name", "creative"], params={"limit": 50})))
        for ad in ads:
            cid = _creative_id(ad)
            vid = None
            if cid:
                try:
                    vid = _video_id(cid)
                except Exception as e:
                    print(f"  ⚠️ [{a.get('name','')[:16]}] 讀 video_id 失敗: {e}")
            spec = copy.get(str(vid)) if vid else None
            if not spec:
                print(f"  ⏭ [{a.get('name','')[:16]}] {ad.get('name','')[:22]} 找不到對應新文案(video {vid}),跳過")
                continue
            print(f"  ✎ [{a.get('name','')[:16]}] video {vid} → 「{spec['headline']}」({len(spec['body'])}字)")
            if C.DRY_RUN:
                continue
            try:
                new_cid = _make_creative(account, vid, spec)
                C.fb_retry(Ad(ad["id"]).api_update, params={"creative": {"creative_id": new_cid}})
                n += 1
                print(f"     ✓ ad {ad['id']} → creative {new_cid}")
            except Exception as e:
                print(f"     ⚠️ 更新失敗: {str(e).replace(chr(10),' ')[:120]}")
    print(f"→ 已換 {n} 支廣告的文案(影片/版位/預算不變,全 PAUSED)。")


def _make_creative(account, video_id, spec):
    vd = {"video_id": video_id, "message": spec["body"], "title": spec["headline"],
          "call_to_action": {"type": "SIGN_UP", "value": {"link": C.LANDING_URL}}}
    thumb = VP.thumbnail(video_id)
    if thumb:
        vd["image_url"] = thumb
    story = {"page_id": C.PAGE_ID, "video_data": vd}
    if C.INSTAGRAM_ID:
        story["instagram_actor_id"] = C.INSTAGRAM_ID
    cp = {"name": spec["headline"], "object_story_spec": story}
    if C.URL_TAGS:
        cp["url_tags"] = C.URL_TAGS
    return C.fb_retry(account.create_ad_creative, params=cp)["id"]


if __name__ == "__main__":
    run()
