"""
把做好的『靜圖廣告』(design/renders/*.png)上成 Meta 圖片廣告。

- 讀 config/static_ads.json(每張圖 = 檔案 + 標題 + 文案)。
- 建一個新的 ABO 圖片 campaign;一個 ad set(≤3 張),ABO 每組 IMAGE_ADSET_BUDGET(預設 500 TWD/日)。
- 定向:台灣 · 30-55 · 繁體中文 · 手動版位(FB/IG Feed+Reels+Stories,不含 Audience Network)。
- 合規:clone 贏家的合規 ad set 繼承台灣廣告主聲明,再覆寫預算/定向/版位。
- 圖直接上傳(create_ad_image)→ 建 link_data 圖片廣告。建完 ACTIVATE=true 就開 ACTIVE。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID …
用法: python launch_static_ads.py
"""
import os, json
import config as C
import launch as L
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.campaign import Campaign

ADSET_BUDGET = float(os.environ.get("IMAGE_ADSET_BUDGET") or 800)   # ABO:每組每日 TWD
ACTIVATE = (os.environ.get("ACTIVATE") or "true").strip().lower() == "true"
AGE_MIN = int(os.environ.get("AGE_MIN") or 30)
AGE_MAX = int(os.environ.get("AGE_MAX") or 55)
# 22 = Traditional Chinese (Taiwan)。已從 Meta targetingsearch 驗證(不是 31=葡萄牙語)。
TW_LOCALE = [int(os.environ.get("TW_LOCALE") or 22)]
DATA = os.path.join(C.ROOT, "config", "static_ads.json")


def targeting():
    return {
        "geo_locations": {"countries": ["TW"]},
        "age_min": AGE_MIN, "age_max": AGE_MAX,
        "locales": TW_LOCALE,
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "facebook_reels", "story"],
        "instagram_positions": ["stream", "reels", "story"],
    }


def make_abo_adset(account, camp, src, name):
    adset_id = L.clone_compliant_adset(account, camp, "tmp", src)
    C.fb_retry(AdSet(adset_id).api_update, params={
        "daily_budget": C.to_minor(ADSET_BUDGET),
        "targeting": targeting(),
    })
    tgt = C.fb_retry(lambda: AdSet(adset_id).api_get(fields=["targeting"]).get("targeting")) or {}
    C.fb_retry(AdSet(adset_id).api_update, params={"name": f"{N.adset_name(tgt)} · {name}"})
    return adset_id


def upload_image(account, path):
    img = C.fb_retry(account.create_ad_image, params={"filename": path})
    if img.get("hash"):
        return img["hash"]
    imgs = img.get("images") or {}
    return next(iter(imgs.values()))["hash"]


def create_image_ad(account, adset_id, image_hash, primary_text, headline, name):
    story = {"page_id": C.PAGE_ID, "link_data": {
        "image_hash": image_hash, "link": C.LANDING_URL,
        "message": primary_text, "name": headline,
        "call_to_action": {"type": "SIGN_UP", "value": {"link": C.LANDING_URL}}}}
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
    print(f"[static] {len(items)} 張靜圖 → ABO 圖片 campaign(1 個 ad set, {ADSET_BUDGET:.0f} TWD/日) | DRY_RUN={C.DRY_RUN}")
    for e in items:
        print(f"  #{e['num']} {e['file']} | {e['headline']}")
    if C.DRY_RUN:
        return

    L.ensure_page_advertiser()
    winners = C.fb_retry(L.find_winner_ads, account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到合規來源(贏家 ad set),無法建容器。")
    src = winners[0]["adset_id"]
    cname = N.campaign_name("Image")
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    adset_id = make_abo_adset(account, camp, src, "組1")
    print(f"  ── ad set {adset_id}(台灣 · 30-55 · 繁中 · 手動版位 · {ADSET_BUDGET:.0f}/日)")

    n = 0
    for e in items:
        path = os.path.join(C.ROOT, e["file"])
        name = N.ad_name("IMG", e["num"], e["theme"])
        try:
            h = upload_image(account, path)
            ad_id = create_image_ad(account, adset_id, h, e["primary_text"], e["headline"], name)
            n += 1
            print(f"     ✓ {name}  ad={ad_id}")
        except Exception as ex:
            print(f"     ⚠️ {name} 建廣告失敗: {ex}")
    print(f"→ 已建 {n}/{len(items)} 張靜圖廣告於 ABO campaign(PAUSED)。")
    if ACTIVATE and n == len(items):
        activate_all(camp)
    elif ACTIVATE:
        print(f"  ⚠️ 只建了 {n}/{len(items)},先不自動開 ACTIVE,留 PAUSED。")


if __name__ == "__main__":
    run()
