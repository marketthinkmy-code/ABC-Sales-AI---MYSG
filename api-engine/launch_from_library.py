"""
用『媒體庫已上傳』的 16 支影片,建一個新的 ABO 影片 campaign(不重新上傳)。

- 影片:直接引用既有 video_id(來自 config/video_ads_16.json),文案用 WK 已確認的 16 份。
- 結構:ABO(預算在 ad set 層,每組 VIDEO_ADSET_BUDGET,預設 500 TWD/日);
        每個 ad set 最多 PER_ADSET(3)支 → 16 支切 6 個 ad set。
- 定向:台灣 · 30-55 · 繁體中文(Chinese Taiwan) · 手動版位(FB/IG 的 Feed+Reels+Stories,不含 Audience Network)。
- 合規:clone 贏家的合規 ad set 繼承台灣廣告主聲明,再覆寫預算/定向/版位/命名。
- 先刪掉同名的舊 campaign(把之前的 CBO 收掉),建好後 ACTIVATE=true 就整個開 ACTIVE。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID …
用法: python launch_from_library.py
"""
import os, json
import config as C
import launch as L
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.advideo import AdVideo
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.campaign import Campaign

ADSET_BUDGET = float(os.environ.get("VIDEO_ADSET_BUDGET") or 500)   # ABO:每組每日 TWD
PER_ADSET = int(os.environ.get("VIDEOS_PER_ADSET") or 3)
ACTIVATE = (os.environ.get("ACTIVATE") or "true").strip().lower() == "true"
AGE_MIN = int(os.environ.get("AGE_MIN") or 30)
AGE_MAX = int(os.environ.get("AGE_MAX") or 55)
TW_LOCALE = [31]   # Chinese (Taiwan) = 繁體
DATA = os.path.join(C.ROOT, "config", "video_ads_16.json")


def targeting():
    """台灣 · 30-55 · 繁中 · 手動高流量版位(FB/IG Feed+Reels+Stories)。不含 Audience Network/Messenger。"""
    return {
        "geo_locations": {"countries": ["TW"]},
        "age_min": AGE_MIN, "age_max": AGE_MAX,
        "locales": TW_LOCALE,
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "facebook_reels", "story"],
        "instagram_positions": ["stream", "reels", "story"],
    }


def thumbnail(video_id):
    try:
        thumbs = C.fb_retry(lambda: list(AdVideo(video_id).get_thumbnails(fields=["uri", "is_preferred"])))
    except Exception:
        thumbs = []
    if not thumbs:
        return None
    pref = next((t["uri"] for t in thumbs if t.get("is_preferred")), None)
    return pref or thumbs[0].get("uri")


def make_abo_adset(account, camp, src, gi):
    """clone 合規 ad set → 覆寫成 ABO 預算 + 台灣/繁中/手動版位 + 依規則命名。"""
    adset_id = L.clone_compliant_adset(account, camp, "tmp", src)
    C.fb_retry(AdSet(adset_id).api_update, params={
        "daily_budget": C.to_minor(ADSET_BUDGET),
        "targeting": targeting(),
    })
    tgt = C.fb_retry(lambda: AdSet(adset_id).api_get(fields=["targeting"]).get("targeting")) or {}
    C.fb_retry(AdSet(adset_id).api_update, params={"name": f"{N.adset_name(tgt)} · 組{gi}"})
    return adset_id


def create_video_ad(account, adset_id, video_id, pt, hl, name):
    vd = {"video_id": video_id, "message": pt, "title": hl,
          "call_to_action": {"type": "SIGN_UP", "value": {"link": C.LANDING_URL}}}
    thumb = thumbnail(video_id)
    if thumb:
        vd["image_url"] = thumb
    story = {"page_id": C.PAGE_ID, "video_data": vd}
    if C.INSTAGRAM_ID:
        story["instagram_actor_id"] = C.INSTAGRAM_ID
    cp = {"name": name, "object_story_spec": story}
    if C.URL_TAGS:
        cp["url_tags"] = C.URL_TAGS
    creative_id = C.fb_retry(account.create_ad_creative, params=cp)["id"]
    return C.fb_retry(account.create_ad, params={
        "name": name, "adset_id": adset_id,
        "creative": {"creative_id": creative_id}, "status": "PAUSED"})["id"]


def activate_all(camp):
    print("  ▶ 開 ACTIVE …")
    adsets = C.fb_retry(lambda: list(Campaign(camp).get_ad_sets(fields=["id"])))
    for a in adsets:
        for ad in C.fb_retry(lambda: list(AdSet(a["id"]).get_ads(fields=["id"]))):
            try:
                C.fb_retry(Ad(ad["id"]).api_update, params={"status": "ACTIVE"})
            except Exception as e:
                print(f"    ⚠️ ad {ad['id']} 開啟失敗: {e}")
        try:
            C.fb_retry(AdSet(a["id"]).api_update, params={"status": "ACTIVE"})
        except Exception as e:
            print(f"    ⚠️ ad set {a['id']} 開啟失敗: {e}")
    C.fb_retry(Campaign(camp).api_update, params={"status": "ACTIVE"})
    print(f"  ✅ campaign + {len(adsets)} 個 ad set + 全部廣告 ACTIVE。")


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    items = json.load(open(DATA, encoding="utf-8"))
    # 平均切成 ceil(N/PER_ADSET) 組(每組≤PER_ADSET),避免出現只有 1 支的組。
    import math
    ng = max(1, math.ceil(len(items) / PER_ADSET))
    groups = [items[i::ng] for i in range(ng)]   # round-robin 均分 → 16 支 = 3,3,3,3,2,2
    print(f"[library] {len(items)} 支影片(引用媒體庫) → {len(groups)} 個 ABO ad set"
          f"(每組≤{PER_ADSET}, {ADSET_BUDGET:.0f} TWD/日) | DRY_RUN={C.DRY_RUN}")
    for gi, g in enumerate(groups, 1):
        print(f"  組{gi}: {[e['name'] for e in g]}")
    if C.DRY_RUN:
        return

    L.ensure_page_advertiser()
    winners = C.fb_retry(L.find_winner_ads, account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到合規來源(贏家 ad set),無法建容器。")
    src = winners[0]["adset_id"]
    cname = N.campaign_name("Video")
    # 收掉舊的同名 campaign(把之前那個 CBO 刪掉)。
    L.delete_existing_campaigns(account, cname)
    # ABO campaign:預算不放 campaign 層(留給 ad set)。
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    n = 0
    for gi, g in enumerate(groups, 1):
        adset_id = make_abo_adset(account, camp, src, gi)
        print(f"  ── 組{gi} ad set {adset_id}(台灣 · 30-55 · 繁中 · 手動版位 · {ADSET_BUDGET:.0f}/日)")
        for e in g:
            name = N.ad_name("VID", e["num"], e["headline"])
            try:
                ad_id = create_video_ad(account, adset_id, e["video_id"],
                                        e["primary_text"], e["headline"], name)
                n += 1
                print(f"     ✓ {name}  ad={ad_id}")
            except Exception as ex:
                print(f"     ⚠️ {name} 建廣告失敗: {ex}")
    print(f"→ 已建 {n}/{len(items)} 支影片廣告於 ABO campaign(PAUSED)。")
    if ACTIVATE and n == len(items):
        activate_all(camp)
    elif ACTIVATE:
        print(f"  ⚠️ 只建了 {n}/{len(items)},先不自動開 ACTIVE,留 PAUSED 待補齊。")


if __name__ == "__main__":
    run()
