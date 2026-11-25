"""
把一個 Drive 資料夾裡「指定」的影片,依 config 分成多個 ad set(每組幾支)上成影片廣告。
文案依檔名對應(人工寫好)。全 PAUSED。

config 格式(見 config/newcontent_copy.json):
  { "campaign_suffix": "...", "adsets": [{"label","videos":[檔名...]}], "copy": {檔名:{theme,headline,primary_text}} }

env: GOOGLE_SA_JSON, META_*, FOLDER_ID, COPY_CONFIG, FOLDER_INTERESTS,
     INTEREST_ADSET_BUDGET(每組/日,預設 800), DRY_RUN(預設 true)
"""
import os, io, json, time
import config as C
import naming as N
import video_pipeline as VP
import launch as L
import launch_interest_winners as W
from facebook_business.adobjects.adaccount import AdAccount

FOLDER_ID = os.environ["FOLDER_ID"]
CFG = json.load(open(os.environ.get("COPY_CONFIG") or
                os.path.join(C.ROOT, "config", "newcontent_copy.json"), encoding="utf-8"))
INTERESTS = (os.environ.get("FOLDER_INTERESTS") or
             "6003127206524,6003389760112,6003371567474").split(",")
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
    vids = {v["name"]: v["id"] for v in list_videos(svc, FOLDER_ID)}
    copy = CFG["copy"]
    adsets = CFG["adsets"]
    cname = f"{N.campaign_name('Video')} · {CFG.get('campaign_suffix', '新Content測試')}"

    print(f"[grouped] 資料夾 {len(vids)} 支 · {len(adsets)} 個 ad set · 每組 {W.BUDGET:.0f}/日 · DRY_RUN={C.DRY_RUN}")
    ok = True
    for g in adsets:
        print(f"  ad set「{g['label']}」:")
        for fn in g["videos"]:
            found = fn in vids
            hasc = fn in copy
            print(f"    · {fn} | 影片{'✓' if found else '✗缺'} 文案{'✓' if hasc else '✗缺'}"
                  + (f" | {copy[fn]['headline']}" if hasc else ""))
            if not (found and hasc):
                ok = False
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / 興趣={INTERESTS} / PAUSED）")
    if C.DRY_RUN:
        print("  (DRY:只列,不下載/不上傳/不建。)")
        return
    if not ok:
        raise SystemExit("有影片或文案缺失,停手(看上面 ✗)。")

    C.init_api()
    account = AdAccount(C.ACT_ID)
    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    total = 0
    for g in adsets:
        aset = W.make_interest_adset(account, camp, f"興趣 · {g['label']}", INTERESTS)
        print(f"  ── ad set {aset}「{g['label']}」({W.BUDGET:.0f}/日)")
        for fn in g["videos"]:
            c = copy[fn]
            tmp = f"/tmp/{vids[fn]}.mp4"
            try:
                sa_download(svc, vids[fn], tmp)
                vid = VP.upload_video(account, tmp)
                VP.wait_ready(vid)
                thumb = VP.thumbnail(vid)
                os.remove(tmp)
                name = N.ad_name("VID", 0, c["theme"][:24])
                ad = C.fb_retry(VP.create_video_ad, account, aset, vid,
                                thumb, c["primary_text"], c["headline"], name)
                total += 1
                print(f"     ✓ {fn} → video {vid} ad {ad}")
            except Exception as e:
                print(f"     ⚠️ {fn} 失敗: {str(e).replace(chr(10),' ')[:140]}")
            time.sleep(PACE)
    print(f"→ 已建 {total} 支影片廣告於「{cname}」({len(adsets)} 個 ad set, PAUSED)。")


if __name__ == "__main__":
    run()
