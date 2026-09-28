"""
完整片測試 —— 開一條新的 ABO campaign,6 支完整敍事廣告各配一個單一興趣 ad set。
影片從 Drive「ABC TW」根目錄(6 支:2/8/16/18/19/20.mp4)抓、上傳 Meta;文案用
config/fullad_copy.json(短句版)。ad set 結構沿用已驗證的 make_interest_adset
(台灣·30-55·繁中·手動版位·單一興趣·advantage_audience=0·pixel+CompleteRegistration·台灣合規)。
全部 PAUSED。

env: DRIVE_FOLDER_ID(預設 ABC TW 根), GOOGLE_SA_JSON, META_ACCESS_TOKEN, PAGE_ID, LANDING_URL,
     INTEREST_ADSET_BUDGET(預設 300), DRY_RUN(預設 true)
用法: DRY_RUN=false python launch_fullad_interest.py
"""
import os, re, time, tempfile
import config as C
import naming as N
import video_pipeline as VP
import launch as L
import launch_interest_winners as W
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign

VP.FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID") or "1b5z9Djj_LR5BZKb501Upvomvffx5_Pqy"  # ABC TW 根
import json
COPY = json.load(open(os.path.join(C.ROOT, "config", "fullad_copy.json"), encoding="utf-8"))

# 影片檔名 → (ad set 標籤, 興趣 id)。用已知的 ICP 興趣 id。
INTEREST_MAP = {
    "2.mp4":  ("中小企業", "6003136069408"),
    "8.mp4":  ("數位行銷", "6003127206524"),
    "16.mp4": ("電子商務", "6003221485467"),
    "18.mp4": ("企業家",   "6003371567474"),
    "19.mp4": ("美業沙龍", "6003088846792"),
    "20.mp4": ("社群行銷", "6003389760112"),
    "7.mp4":  ("新創公司", "6003325004380"),
    "9.mp4":  ("Shopify店家", "6003230166788"),
    "15.mp4": ("數位行銷B", "6003127206524"),
}
ORDER = ["2.mp4", "8.mp4", "16.mp4", "18.mp4", "19.mp4", "20.mp4",
         "7.mp4", "9.mp4", "15.mp4"]
PACE = float(os.environ.get("PACE_SEC") or 3)
# APPEND_ONLY:只建這幾支(逗號分隔檔名),且不刪同名 campaign,沿用現有的(補片用)。
APPEND_ONLY = [s.strip() for s in (os.environ.get("APPEND_ONLY") or "").split(",") if s.strip()]
# FULLAD_CAMPAIGN_ID:直接指定要補進的 campaign id(繞過用日期組的名稱去找,避免跨日建到新 campaign)。
TARGET_CAMPAIGN_ID = (os.environ.get("FULLAD_CAMPAIGN_ID") or "").strip()
# DELETE_CAMPAIGN_ID:先刪掉這個 campaign(清掉之前誤建的那條)。
DELETE_CAMPAIGN_ID = (os.environ.get("DELETE_CAMPAIGN_ID") or "").strip()
# DELETE_ADSET_IDS:先刪掉這些 ad set(清掉上傳失敗留下的空 ad set)。
DELETE_ADSET_IDS = [s.strip() for s in (os.environ.get("DELETE_ADSET_IDS") or "").split(",") if s.strip()]


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    svc = VP.drive_service()
    found = {f["name"]: f for f in VP.list_videos(svc)}
    cname = f"{N.campaign_name('Video')} · 完整片測試 · T1"

    print(f"[fullad] folder {VP.FOLDER_ID} · 找到 {len(found)} 支影片 · 每組 {W.BUDGET:.0f}/日 "
          f"· APPEND_ONLY={APPEND_ONLY or '(整批)'} · DRY_RUN={C.DRY_RUN}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / PAUSED）")
    plan = [fn for fn in ORDER if fn in found and fn in COPY]
    if APPEND_ONLY:
        plan = [fn for fn in plan if fn in APPEND_ONLY]
    for fn in plan:
        lbl, iid = INTEREST_MAP[fn]
        print(f"    · {fn} → 興趣「{lbl}」({iid})｜「{COPY[fn]['headline']}」")
    missing = [fn for fn in ORDER if fn not in found]
    if missing:
        print(f"  ⚠️ 資料夾找不到:{missing}")
    if C.DRY_RUN:
        print("  (DRY:只排組,未上傳、未建。DRY_RUN=false 才真的做。)")
        return
    if not plan:
        raise SystemExit("沒有可上的影片(對不到檔名/文案)。")

    L.ensure_page_advertiser()
    from facebook_business.adobjects.adset import AdSet
    for aid in DELETE_ADSET_IDS:
        try:
            AdSet(aid).api_delete()
            print(f"  🗑 已刪除空 ad set {aid}")
        except Exception as e:
            print(f"  ⚠️ 刪 ad set {aid} 失敗: {str(e)[:100]}")
    if DELETE_CAMPAIGN_ID:
        try:
            Campaign(DELETE_CAMPAIGN_ID).api_delete()
            print(f"  🗑 已刪除誤建的 campaign {DELETE_CAMPAIGN_ID}")
        except Exception as e:
            print(f"  ⚠️ 刪除 {DELETE_CAMPAIGN_ID} 失敗: {str(e)[:100]}")
    camp = TARGET_CAMPAIGN_ID or (VP.find_campaign(account, cname) if APPEND_ONLY else None)
    if camp:
        print(f"  ↺ APPEND：補進現有 campaign {camp}")
    else:
        if not APPEND_ONLY:
            L.delete_existing_campaigns(account, cname)
        camp = C.fb_retry(account.create_campaign, params={
            "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
            "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
        })["id"]
        print(f"  ✓ ABO campaign {camp}: {cname}")

    n = 0
    for fn in plan:
        lbl, iid = INTEREST_MAP[fn]
        spec = COPY[fn]
        try:
            aset = W.make_interest_adset(account, camp, f"興趣 · {lbl}", [iid])
        except Exception as e:
            print(f"  ⚠️ [{lbl}] ad set 建立失敗: {str(e).replace(chr(10),' ')[:120]}")
            continue
        print(f"  ── {lbl} ad set {aset}")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, re.sub(r"[^\w.-]", "_", fn))
            try:
                VP.download(svc, found[fn]["id"], p)
                vid = C.fb_retry(VP.upload_video, account, p)
                print(f"     ↑ {fn} → video {vid} 等待處理…")
                if not VP.wait_ready(vid):
                    print("       ⚠️ 影片處理逾時,跳過(可重跑)")
                    continue
                name = N.ad_name("VID", 0, spec.get("theme") or fn)
                ad = C.fb_retry(VP.create_video_ad, account, aset, vid,
                                VP.thumbnail(vid), spec["body"], spec["headline"], name)
                n += 1
                print(f"       ✓ 廣告 ad={ad}")
            except Exception as e:
                print(f"       ⚠️ {fn} 失敗: {str(e).replace(chr(10),' ')[:120]}")
        time.sleep(PACE)
    print(f"→ 已建 {n}/{len(plan)} 支完整片廣告(各 1 興趣 ad set,全 PAUSED)。")


if __name__ == "__main__":
    run()
