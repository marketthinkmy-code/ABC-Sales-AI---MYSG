"""
廣受眾 Advantage+ campaign —— 放寬受眾(不鎖興趣、advantage_audience=1、Advantage+ 版位),
把「之前 re-upload 的完整片 + reeve 等已過審的 creative」全丟進一個廣 ad set,讓 Meta 自己找便宜量。

目的:CPL 這兩天變貴(多半是 CPM 季節性上漲),用廣受眾去找更便宜的庫存、分散疲勞。

- 從 SOURCE_CAMPAIGNS 的現有廣告收 creative(引用 creative_id,不重做素材),
  只收「已過審」的(跳過 DISAPPROVED / WITH_ISSUES / PENDING_REVIEW),用 video_id 去重。
- 新開 1 條 ABO campaign + 1 個廣 ad set(台灣 · 25-55 · 繁中 · Advantage+ 受眾/版位 · pixel+CompleteRegistration)。
- 全 PAUSED。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID,
     SOURCE_CAMPAIGNS(逗號分隔,預設 完整片測試 + reeve),
     BROAD_BUDGET(預設 1000), AGE_MIN(25), AGE_MAX(55), DRY_RUN(預設 true)
用法: DRY_RUN=false python launch_broad_advantage.py
"""
import os, time
import config as C
import naming as N
import launch as L
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adcreative import AdCreative

SOURCE_CAMPAIGNS = [s.strip() for s in (os.environ.get("SOURCE_CAMPAIGNS") or
                    "120247263797180658,120247964979690658").split(",") if s.strip()]
BUDGET = float(os.environ.get("BROAD_BUDGET") or 1000)
AGE_MIN = int(os.environ.get("AGE_MIN") or 25)
AGE_MAX = int(os.environ.get("AGE_MAX") or 55)
TW_LOCALE = [int(os.environ.get("TW_LOCALE") or 22)]
PIXEL = os.environ.get("INTEREST_PIXEL") or C.PIXEL_ID
EVENT = os.environ.get("INTEREST_EVENT") or "COMPLETE_REGISTRATION"
PACE = float(os.environ.get("PACE_SEC") or 3)
# 已過審(可用)的狀態;其餘(DISAPPROVED/WITH_ISSUES/PENDING_REVIEW/PENDING_BILLING_INFO…)跳過
OK_STATUS = {"ACTIVE", "PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED"}


def _cid(cr):
    if not cr:
        return None
    try:
        return cr["id"]
    except Exception:
        return cr.get("id") if hasattr(cr, "get") else None


def creative_video_id(cid):
    try:
        cr = C.fb_retry(lambda: AdCreative(cid).api_get(fields=["video_id", "object_story_spec"]))
        if cr.get("video_id"):
            return str(cr["video_id"])
        oss = cr.get("object_story_spec") or {}
        vd = oss.get("video_data") or {}
        if vd.get("video_id"):
            return str(vd["video_id"])
    except Exception:
        pass
    return None


def gather(account):
    out, seen = [], set()
    for camp in SOURCE_CAMPAIGNS:
        try:
            ads = C.fb_retry(lambda: list(Campaign(camp).get_ads(
                fields=["name", "creative", "effective_status"], params={"limit": 200})))
        except Exception as e:
            print(f"  ⚠️ campaign {camp} 讀不到: {str(e)[:100]}")
            continue
        for a in ads:
            crid = _cid(a.get("creative"))
            st = a.get("effective_status")
            if not crid or st not in OK_STATUS:
                print(f"     ⏭ 跳過（{st}）{(a.get('name') or '')[:40]}")
                continue
            vid = creative_video_id(crid)
            key = vid or crid
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": a.get("name") or "", "cid": crid, "vid": vid, "st": st})
    return out


def broad_targeting():
    # 不鎖興趣;advantage_audience=1 讓 Meta 擴充;不指定 positions → Advantage+ 版位。
    return {
        "geo_locations": {"countries": ["TW"]},
        "age_min": AGE_MIN, "age_max": AGE_MAX,
        "locales": TW_LOCALE,
        "targeting_automation": {"advantage_audience": 1},
    }


def make_broad_adset(account, camp, name):
    params = {
        "name": name, "campaign_id": camp,
        "billing_event": "IMPRESSIONS", "optimization_goal": "OFFSITE_CONVERSIONS",
        "daily_budget": C.to_minor(BUDGET),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "promoted_object": {"pixel_id": PIXEL, "custom_event_type": EVENT},
        "targeting": broad_targeting(),
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
    cname = f"{N.campaign_name('Video')} · 廣受眾Advantage+ · T1"

    print(f"[廣受眾A+] 來源 campaign={SOURCE_CAMPAIGNS} · 每組 {BUDGET:.0f}/日 · 年齡 {AGE_MIN}-{AGE_MAX} · DRY_RUN={C.DRY_RUN}")
    creatives = gather(account)
    print(f"  → 收到 {len(creatives)} 支已過審、不重複的 creative:")
    for c in creatives:
        print(f"     ✓ ({c['st']}) creative={c['cid']} video={c['vid']}  ← {c['name'][:48]}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / 廣受眾 advantage_audience=1 / Advantage+ 版位 / PAUSED）")
    if C.DRY_RUN:
        print("  (DRY:只配對,未建。DRY_RUN=false 才真的建。)")
        return
    if not creatives:
        raise SystemExit("沒收到可用 creative,停手。")

    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    aset = make_broad_adset(account, camp, f"廣受眾 · 台灣 {AGE_MIN}-{AGE_MAX} · A+")
    print(f"  ── ad set {aset}（台灣 · {AGE_MIN}-{AGE_MAX} · 繁中 · Advantage+ 受眾/版位 · {BUDGET:.0f}/日）")

    n = 0
    for i, c in enumerate(creatives, 1):
        nm = N.ad_name("VID", i, "廣受眾A+·" + (c["name"].split("|")[-1].strip()[:20] if "|" in c["name"] else c["name"][:20]))
        try:
            ad = C.fb_retry(account.create_ad, params={
                "name": nm, "adset_id": aset,
                "creative": {"creative_id": c["cid"]}, "status": "PAUSED"})
            n += 1
            print(f"     ✓ 引用 {c['cid']}(video {c['vid']}) → ad {ad['id']}")
        except Exception as e:
            print(f"     ⚠️ {c['cid']} 失敗: {str(e).replace(chr(10),' ')[:120]}")
        time.sleep(PACE)
    print(f"→ 已建 {n}/{len(creatives)} 支廣告於廣受眾 Advantage+ ad set（PAUSED）。")


if __name__ == "__main__":
    run()
