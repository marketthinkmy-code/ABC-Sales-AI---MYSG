"""
一次性修正:fill_interest_drive 那次因 Meta 限流(code=17)只讀到 7 支 ad set,
導致 中小企業 多一支 Hook⑧、社群行銷 沒拿到。這支用『已上傳的 video_id』做外科手術:
  1. 刪掉指定的重複廣告(FIX_DELETE_ADS)。
  2. 對指定 ad set(FIX_ADD):先清掉它現有廣告,再放上對應 hook(引用既有 video_id)。
不重新上傳影片,只補位。全 PAUSED。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, ANTHROPIC_API_KEY,
     FILL_CAMPAIGN_ID(預設興趣測試 T1),
     FIX_DELETE_ADS(逗號分隔 ad id), FIX_ADD(JSON), DRY_RUN(預設 true)
"""
import os, re, json, time
import config as C
import naming as N
import video_pipeline as VP
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adaccount import AdAccount

CAMP_ID = os.environ.get("FILL_CAMPAIGN_ID") or "120247254989860658"
DELETE_ADS = [s.strip() for s in (os.environ.get("FIX_DELETE_ADS") or "").split(",") if s.strip()]
# 預設補位:社群行銷 ← Hook⑧(8.mp4),用該次已上傳的 video_id。
# 直接指定 adset_id(社群行銷 120247254994310658),因為 campaign.get_ad_sets 一直漏讀這支。
ADD = json.loads(os.environ.get("FIX_ADD") or
                 '[{"adset_id":"120247254994310658","file":"8.mp4","video_id":"1591571939123690"}]')


def _hook_map():
    try:
        return json.load(open(os.path.join(C.ROOT, "config", "hook_map.json"), encoding="utf-8"))
    except Exception:
        return {}


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    hmap = _hook_map()
    guard = ("（文案守則:不 overpromise——講「把漏掉的接回來／多接住幾單」,"
             "不要保證成交、不要說一單不漏。全繁體中文。）")

    adsets = C.fb_retry(lambda: list(
        Campaign(CAMP_ID).get_ad_sets(fields=["id", "name"], params={"limit": 100})))
    print(f"[fix] campaign {CAMP_ID} · 讀到 {len(adsets)} 支 ad set · "
          f"刪 {len(DELETE_ADS)} 支重複 · 補 {len(ADD)} 支 · DRY_RUN={C.DRY_RUN}")
    for a in adsets:
        print(f"    - {a.get('name','')}  ({a['id']})")
    for spec in ADD:
        if spec.get("adset_id"):
            print(f"    補:{spec['file']} → 直接指定 ad set {spec['adset_id']}")
        else:
            m = [a for a in adsets if spec["adset_match"] in (a.get("name") or "")]
            print(f"    補:{spec['file']} → ad set「{spec['adset_match']}」找到 {len(m)} 支")
    if C.DRY_RUN:
        print("  (DRY:未動。DRY_RUN=false 才真的改。)")
        return

    for aid in DELETE_ADS:
        try:
            Ad(aid).api_delete()
            print(f"  ✓ 刪掉重複廣告 {aid}")
        except Exception as e:
            print(f"  ⚠️ 刪 {aid} 失敗: {e}")

    for spec in ADD:
        if spec.get("adset_id"):
            a = {"id": spec["adset_id"], "name": spec["adset_id"]}
        else:
            targets = [x for x in adsets if spec["adset_match"] in (x.get("name") or "")]
            if not targets:
                print(f"  ⚠️ 找不到 ad set 含「{spec['adset_match']}」,跳過")
                continue
            a = targets[0]
        # 先清掉這支 ad set 現有廣告(把舊 repo 影片換掉)
        for ad in C.fb_retry(lambda: list(AdSet(a["id"]).get_ads(fields=["id"], params={"limit": 200}))):
            try:
                Ad(ad["id"]).api_delete()
            except Exception:
                pass
        meta = hmap.get(spec["file"], {})
        hint = (meta.get("hook", spec["file"]) + guard)
        theme = meta.get("theme") or spec["file"]
        num = int(re.sub(r"\D", "", spec["file"]) or 0)
        try:
            pt, hl = VP.write_copy(hint)
            name = N.ad_name("VID", num, theme)
            ad_id = C.fb_retry(VP.create_video_ad, account, a["id"], spec["video_id"],
                               VP.thumbnail(spec["video_id"]), pt, hl, name)
            print(f"  ✓ [{a.get('name','')}] {name}  ad={ad_id}")
        except Exception as e:
            print(f"  ⚠️ 補 {spec['file']} 失敗: {e}")
        time.sleep(3)

    print("→ 修正完成(全 PAUSED)。")


if __name__ == "__main__":
    run()
