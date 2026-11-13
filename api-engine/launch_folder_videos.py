"""
把一個 Drive 資料夾裡的所有影片,上成 Meta 影片廣告(一個 campaign、一個 ad set,hook 測試)。
文案用 config(人工寫好,依檔名對應),不叫 AI 生。全 PAUSED。

- SA 列資料夾影片 → 逐支下載、上傳成 Meta ad video。
- 新開 1 條 ABO campaign + 1 個興趣 ad set(買家來源興趣:數位行銷/社群/企業家)。
- 6 支擠一組 = 讓 Meta 比哪個 hook 勝出。

env: GOOGLE_SA_JSON, META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID,
     FOLDER_ID, COPY_CONFIG(預設 config/newhook_copy.json), FOLDER_INTERESTS,
     FOLDER_BUDGET(預設 1000), FOLDER_CAMP_SUFFIX(預設 新Hook測試), DRY_RUN(預設 true)
用法: DRY_RUN=false FOLDER_ID=xxx python launch_folder_videos.py
"""
import os, io, json, time
import config as C
import naming as N
import video_pipeline as VP
import launch as L
import launch_interest_winners as W
from facebook_business.adobjects.adaccount import AdAccount

FOLDER_ID = os.environ["FOLDER_ID"]
COPY = json.load(open(os.environ.get("COPY_CONFIG") or
                os.path.join(C.ROOT, "config", "newhook_copy.json"), encoding="utf-8"))
# 數位行銷 / 社群媒體行銷 / 企業家(付款學員數據裡帶買家最多的興趣)
INTERESTS = (os.environ.get("FOLDER_INTERESTS") or
             "6003127206524,6003389760112,6003371567474").split(",")
SUFFIX = os.environ.get("FOLDER_CAMP_SUFFIX") or "新Hook測試"
PACE = float(os.environ.get("PACE_SEC") or 4)


def sa_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_videos(svc, folder):
    out, tok = [], None
    while True:
        resp = svc.files().list(
            q=f"'{folder}' in parents and trashed=false and mimeType contains 'video/'",
            fields="nextPageToken, files(id,name)", pageSize=200,
            supportsAllDrives=True, includeItemsFromAllDrives=True, pageToken=tok).execute()
        out += resp.get("files", [])
        tok = resp.get("nextPageToken")
        if not tok:
            break
    return out


def sa_download(svc, fid, path):
    from googleapiclient.http import MediaIoBaseDownload
    req = svc.files().get_media(fileId=fid, supportsAllDrives=True)
    with io.FileIO(path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=16 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def run():
    svc = sa_service()
    vids = list_videos(svc, FOLDER_ID)
    cname = f"{N.campaign_name('Video')} · {SUFFIX} · T1"
    print(f"[folder] 資料夾 {FOLDER_ID}: {len(vids)} 支影片 · 每組 {W.BUDGET:.0f}/日 · DRY_RUN={C.DRY_RUN}")
    plan = []
    for v in vids:
        c = COPY.get(v["name"])
        plan.append((v, c))
        print(f"  · {v['name']} → {'✓ '+c['headline'] if c else '✗ 無對應文案(會跳過)'}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / 興趣={INTERESTS} / PAUSED）")
    if C.DRY_RUN:
        print("  (DRY:只列,不下載/不上傳/不建。)")
        return

    C.init_api()
    account = AdAccount(C.ACT_ID)
    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")
    aset = W.make_interest_adset(account, camp, "興趣 · 數位行銷+社群+企業家", INTERESTS)
    print(f"  ── ad set {aset}（台灣 · 30-55 · 繁中 · 手動版位 · {W.BUDGET:.0f}/日）")

    n = 0
    for v, c in plan:
        if not c:
            print(f"     ⏭ {v['name']} 無文案,跳過")
            continue
        tmp = f"/tmp/{v['id']}.mp4"
        try:
            sa_download(svc, v["id"], tmp)
            vid = VP.upload_video(account, tmp)
            VP.wait_ready(vid)
            thumb = VP.thumbnail(vid)
            os.remove(tmp)
            name = N.ad_name("VID", 0, c["theme"][:24])
            ad = C.fb_retry(VP.create_video_ad, account, aset, vid,
                            thumb, c["primary_text"], c["headline"], name)
            n += 1
            print(f"     ✓ {v['name']} → video {vid} ad {ad}")
        except Exception as e:
            print(f"     ⚠️ {v['name']} 失敗: {str(e).replace(chr(10),' ')[:140]}")
        time.sleep(PACE)
    print(f"→ 已建 {n}/{len(plan)} 支影片廣告於「{cname}」(PAUSED)。")


if __name__ == "__main__":
    run()
