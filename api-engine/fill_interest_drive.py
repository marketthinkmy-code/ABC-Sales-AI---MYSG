"""
把 Drive「hook」資料夾裡的『真實影片』上傳到 Meta,塞進「興趣測試」campaign 那 8 支興趣 ad set。
(對照 fill_interest_ads:那支是引用 repo 現成 video_id;這支是從你的 Drive 資料夾現抓現上。)

流程:
  1. 用 SA 掃 DRIVE_FOLDER_ID 的影片(video_pipeline.list_videos)。
  2. 每支:AI 產長文案(write_copy) → 下載 → 上傳 Meta(upload_video) → 等處理完成(wait_ready)。
     每支只上傳『一次』,拿到一個 video_id,之後在多個 ad set 引用同一個 video_id。
  3. 取目標 campaign 的 ad set;REPLACE=true 先清掉裡面現有廣告(把 B 方案那批 repo 影片換掉)。
  4. 依 DIST_MODE 分配:
       each  = 每支 ad set 都放『全部』folder 影片(同素材測所有興趣受眾,最乾淨) [預設]
       spread= folder 影片輪流分散到各 ad set(數量多、想省錢時用)
  全部 PAUSED(ACTIVATE=true 才開 ACTIVE)。

env: DRIVE_FOLDER_ID(預設 hook 資料夾), GOOGLE_SA_JSON, ANTHROPIC_API_KEY, META_ACCESS_TOKEN,
     PAGE_ID, LANDING_URL, PIXEL_ID, FILL_CAMPAIGN_ID(預設興趣測試 T1),
     DIST_MODE(each/spread,預設 each), REPLACE(預設 true), ACTIVATE(預設 false), DRY_RUN(預設 true)
用法: DRY_RUN=false python fill_interest_drive.py
"""
import os, re, time, tempfile
import config as C
import naming as N
import video_pipeline as VP
import launch_from_library as LIB
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad

# 覆寫 VP 的資料夾為你的「hook」資料夾(env 沒設就用這個)。
HOOK_FOLDER = os.environ.get("DRIVE_FOLDER_ID") or "1iQvsvtI_H78v66r8dngorRSSpQQ72uZx"
VP.FOLDER_ID = HOOK_FOLDER
CAMP_ID = os.environ.get("FILL_CAMPAIGN_ID") or "120247254989860658"   # 興趣測試 · T1
DIST_MODE = (os.environ.get("DIST_MODE") or "each").strip().lower()
REPLACE = (os.environ.get("REPLACE") or "true").strip().lower() == "true"
ACTIVATE = (os.environ.get("ACTIVATE") or "false").strip().lower() == "true"
PACE = float(os.environ.get("PACE_SEC") or 3)


def target_adsets():
    a = C.fb_retry(lambda: list(
        Campaign(CAMP_ID).get_ad_sets(fields=["id", "name"], params={"limit": 100})))
    return sorted(a, key=lambda x: x["id"])


def clear_ads(adset_id):
    for ad in C.fb_retry(lambda: list(AdSet(adset_id).get_ads(fields=["id"], params={"limit": 200}))):
        try:
            Ad(ad["id"]).api_delete()
        except Exception:
            pass


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    svc = VP.drive_service()
    vids = VP.list_videos(svc)
    vids.sort(key=lambda f: f["name"])
    adsets = target_adsets()

    print(f"[fill-drive] folder {HOOK_FOLDER} · 影片 {len(vids)} 支 · "
          f"campaign {CAMP_ID} · {len(adsets)} 支 ad set · mode={DIST_MODE} · "
          f"replace={REPLACE} · activate={ACTIVATE} · DRY_RUN={C.DRY_RUN}")
    for f in vids:
        print(f"    · {f['name']}")
    if not vids:
        print("  ⚠️ 資料夾沒有影片(或 SA 沒讀取權限)。把資料夾分享給 "
              "twabc-ads-bot@abctwai.iam.gserviceaccount.com,或改用 DRIVE_FOLDER_ID。")
        return
    if not adsets:
        raise SystemExit(f"campaign {CAMP_ID} 底下找不到 ad set。")
    if C.DRY_RUN:
        print(f"  分配預覽(mode={DIST_MODE}):")
        if DIST_MODE == "each":
            print(f"    每支 ad set 都放全部 {len(vids)} 支影片 → 共 {len(vids)*len(adsets)} 則廣告")
        else:
            for i, a in enumerate(adsets):
                mine = [f["name"] for j, f in enumerate(vids) if j % len(adsets) == i]
                print(f"    {a.get('name','')[:28]:<28} ← {mine}")
        print("  (DRY:只讀資料夾+排組,未產文案、未上傳、未建。DRY_RUN=false 才真的做。)")
        return

    # 1) 每支影片上傳一次,拿 video_id + 縮圖 + 文案
    assets = []
    for i, f in enumerate(vids, 1):
        fid, fname = f["id"], f["name"]
        try:
            pt, hl = VP.write_copy(fname)
        except Exception as e:
            print(f"  ⚠️ {fname} 產文案失敗,跳過: {e}")
            continue
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, re.sub(r"[^\w.-]", "_", fname))
            try:
                VP.download(svc, fid, p)
                vid = C.fb_retry(VP.upload_video, account, p)
                print(f"  ↑ {fname}｜標題:{hl}｜文案{len(pt)}字｜video={vid} 等待處理…")
                if not VP.wait_ready(vid):
                    print("    ⚠️ 影片處理逾時,先跳過(稍後可重跑)")
                    continue
                assets.append({"num": i, "fname": fname, "video_id": vid,
                               "thumb": VP.thumbnail(vid), "pt": pt, "hl": hl})
            except Exception as e:
                print(f"    ⚠️ {fname} 上傳失敗,跳過: {e}")
        time.sleep(PACE)

    if not assets:
        raise SystemExit("沒有任何影片成功上傳,停手。")
    print(f"  ✓ 成功上傳 {len(assets)} 支影片,開始塞進 ad set")

    # 2) 分配到 ad set
    if REPLACE:
        for a in adsets:
            clear_ads(a["id"])
        print(f"  🧹 已清掉 {len(adsets)} 支 ad set 的舊廣告(換成 hook 影片)")

    n = 0
    for i, a in enumerate(adsets):
        mine = assets if DIST_MODE == "each" else [x for j, x in enumerate(assets) if j % len(adsets) == i]
        for x in mine:
            theme = re.sub(r"\s+", "", x["hl"])[:24] or x["fname"][:16]
            name = N.ad_name("VID", x["num"], theme)
            try:
                ad_id = C.fb_retry(VP.create_video_ad, account, a["id"], x["video_id"],
                                   x["thumb"], x["pt"], x["hl"], name)
                n += 1
                print(f"     ✓ [{a.get('name','')[:16]}] {name}  ad={ad_id}")
            except Exception as e:
                print(f"     ⚠️ [{a.get('name','')[:16]}] {name} 失敗: {str(e).replace(chr(10),' ')[:100]}")
            time.sleep(PACE)

    print(f"→ 已塞 {n} 則影片廣告進 {len(adsets)} 支興趣 ad set(全 PAUSED)。")
    if ACTIVATE and n:
        LIB.activate_all(CAMP_ID)


if __name__ == "__main__":
    run()
