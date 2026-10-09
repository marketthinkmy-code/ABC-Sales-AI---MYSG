"""
地區測試 —— 用台灣已驗證的贏家影片(M1Video9),開一條新 ABO campaign,
分「北部(雙北+桃園)」「中南部(台中+彰化+台南+高雄)」兩個地區 ad set,
各自在地文案,同預算,比哪一區 CPL 低。全部 PAUSED。

- 地區用 Meta adgeolocation 的 region(縣市)key,腳本用 TargetingSearch 動態解析。
- ad set 沿用已驗證的台灣合規參數(pixel + CompleteRegistration + 台灣受益人/付款人),
  人口/版位照舊(30-55 · 繁中 locale22 · 手動版位),advantage_audience=0(用我給的地區+人口,不外擴)。
- 影片引用既有 video_id(config/geo_test.json),文案用在地版。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID,
     GEO_ADSET_BUDGET(預設 500), DRY_RUN(預設 true)
用法: DRY_RUN=false python launch_geo_test.py
"""
import os, json, re, time
import config as C
import naming as N
import video_pipeline as VP
import launch as L
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.targetingsearch import TargetingSearch

DATA = json.load(open(os.path.join(C.ROOT, "config", "geo_test.json"), encoding="utf-8"))
BUDGET = float(os.environ.get("GEO_ADSET_BUDGET") or 500)
PACE = float(os.environ.get("PACE_SEC") or 3)
PIXEL = os.environ.get("INTEREST_PIXEL") or C.PIXEL_ID
EVENT = os.environ.get("INTEREST_EVENT") or "COMPLETE_REGISTRATION"


def resolve_region(name):
    """用 TargetingSearch 找台灣的 region(縣市)key。回 (key, 回傳的名稱) 或 (None, None)。"""
    try:
        rows = TargetingSearch.search(params={
            "q": name, "type": "adgeolocation", "location_types": ["region"], "limit": 25})
    except Exception as e:
        print(f"    (region 查詢失敗 {name}: {str(e)[:80]})")
        return None, None
    tw = [r for r in rows if (r.get("country_code") == "TW")]
    # 先找名稱含查詢字的,否則取第一個台灣 region
    for r in tw:
        if name.lower() in (r.get("name") or "").lower():
            return r.get("key"), r.get("name")
    if tw:
        return tw[0].get("key"), tw[0].get("name")
    return None, None


def geo_targeting(region_keys):
    return {
        "geo_locations": {"regions": [{"key": k} for k in region_keys]},
        "age_min": 30, "age_max": 55,
        "locales": [22],
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "facebook_reels", "story"],
        "instagram_positions": ["stream", "reels", "story"],
        "targeting_automation": {"advantage_audience": 0},
    }


def make_geo_adset(account, camp, name, region_keys):
    params = {
        "name": name, "campaign_id": camp,
        "billing_event": "IMPRESSIONS", "optimization_goal": "OFFSITE_CONVERSIONS",
        "daily_budget": C.to_minor(BUDGET),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "promoted_object": {"pixel_id": PIXEL, "custom_event_type": EVENT},
        "targeting": geo_targeting(region_keys),
        "status": "PAUSED",
        "regional_regulated_categories": ["TAIWAN_UNIVERSAL"],
        "regional_regulation_identities": {
            "taiwan_universal_beneficiary": C.BUSINESS_ID,
            "taiwan_universal_payer": C.BUSINESS_ID,
        },
    }
    return C.fb_retry(account.create_ad_set, params=params)["id"]


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    vid = DATA["winner_video_id"]
    cname = f"{N.campaign_name('Video')} · 地區測試 · T1"

    # 解析每個 cluster 的 region keys
    resolved = []
    for cl in DATA["clusters"]:
        keys, names = [], []
        for rname in cl["regions"]:
            k, nm = resolve_region(rname)
            if k:
                keys.append(k)
                names.append(nm or rname)
            else:
                print(f"  ⚠️ 找不到 region: {rname}")
        resolved.append({**cl, "keys": keys, "names": names})

    print(f"[地區測試] 影片 {vid}（{DATA.get('winner_note','')}）· 每組 {BUDGET:.0f}/日 · DRY_RUN={C.DRY_RUN}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / PAUSED）")
    for cl in resolved:
        print(f"    · {cl['label']}｜地區={cl['names']}（keys={cl['keys']}）｜「{cl['headline']}」")
    if C.DRY_RUN:
        print("  (DRY:只解析+排組,未建。DRY_RUN=false 才真的建。)")
        return
    if any(not cl["keys"] for cl in resolved):
        raise SystemExit("有 cluster 的地區沒解析到 key,停手(先看 dry-run 的解析結果)。")

    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    thumb = VP.thumbnail(vid)
    n = 0
    for cl in resolved:
        try:
            aset = make_geo_adset(account, camp, f"地區 · {cl['label']}", cl["keys"])
        except Exception as e:
            print(f"  ⚠️ [{cl['label']}] ad set 建立失敗: {str(e).replace(chr(10),' ')[:140]}")
            continue
        print(f"  ── {cl['label']} ad set {aset}（{cl['names']}）")
        name = N.ad_name("VID", 0, re.sub(r"\s+", "", cl["headline"])[:24])
        try:
            ad = C.fb_retry(VP.create_video_ad, account, aset, vid, thumb, cl["body"], cl["headline"], name)
            n += 1
            print(f"       ✓ 廣告 ad={ad}")
        except Exception as e:
            print(f"       ⚠️ 建廣告失敗: {str(e).replace(chr(10),' ')[:140]}")
        time.sleep(PACE)
    print(f"→ 已建 {n}/{len(resolved)} 個地區 ad set（各 1 支贏家影片,全 PAUSED）。")


if __name__ == "__main__":
    run()
