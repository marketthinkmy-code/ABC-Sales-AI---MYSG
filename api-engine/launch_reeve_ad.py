"""
把 Drive 的「reeve style.mov」(揭祕後台型影片)上成一支 Meta 影片廣告。

- 下載 Drive 影片(SA, supportsAllDrives)→ 上傳成 Meta ad video。
- 新開一條 ABO video campaign,1 個興趣 ad set(台灣合規/人口/版位/pixel+CompleteRegistration)。
- 受眾鎖「課程導師/教練/知識付費」那一路:企業家 + 數位行銷 + 社群媒體行銷 + 中小企業。
- 文案用 config/reeve_copy.json(人工寫好的,不叫 AI 生)。全 PAUSED。

env: GOOGLE_SA_JSON, META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID,
     INTEREST_ADSET_BUDGET(預設 800), DRY_RUN(預設 true)
用法: DRY_RUN=false python launch_reeve_ad.py
"""
import os, io, json
import config as C
import naming as N
import video_pipeline as VP
import launch as L
import launch_interest_winners as W
from facebook_business.adobjects.adaccount import AdAccount

COPY = json.load(open(os.path.join(C.ROOT, "config", "reeve_copy.json"), encoding="utf-8"))
FILE_ID = os.environ.get("REEVE_FILE_ID") or COPY["file_id"]
# 企業家 / 數位行銷 / 社群媒體行銷 / 中小企業
INTEREST_IDS = (os.environ.get("REEVE_INTERESTS") or
                "6003371567474,6003127206524,6003389760112,6003136069408").split(",")
ADSET_LABEL = os.environ.get("REEVE_ADSET_LABEL") or "企業家+數位行銷+社群+中小企業"


def sa_download(fid, path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    req = svc.files().get_media(fileId=fid, supportsAllDrives=True)
    with io.FileIO(path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=20 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    cname = f"{N.campaign_name('Video')} · 課程導師揭祕 · T1"
    hl, pt = COPY["headline"], COPY["primary_text"]

    print(f"[reeve] 影片 {COPY.get('source')} ({FILE_ID}) → 1 支影片廣告 · 每組 {W.BUDGET:.0f}/日 · DRY_RUN={C.DRY_RUN}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / PAUSED）")
    print(f"  興趣 ad set: {ADSET_LABEL}（{','.join(INTEREST_IDS)}）")
    print(f"  標題: {hl}")
    print(f"  內文首行: {pt.splitlines()[0]}")
    if C.DRY_RUN:
        print("  (DRY:只印計畫,不下載/不上傳/不建。DRY_RUN=false 才真的做。)")
        return

    tmp = "/tmp/reeve_src.mov"
    print("  下載影片中…")
    sa_download(FILE_ID, tmp)
    print(f"  ✓ 下載完成 {os.path.getsize(tmp)} bytes，上傳到 Meta…")
    vid = VP.upload_video(account, tmp)
    print(f"  ✓ ad video {vid}，等待轉檔 ready…")
    if not VP.wait_ready(vid):
        print("  ⚠️ 影片還沒 ready（可能仍在處理),仍嘗試建廣告。")
    thumb = VP.thumbnail(vid)
    try:
        os.remove(tmp)
    except Exception:
        pass

    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    aset = W.make_interest_adset(account, camp, f"興趣 · {ADSET_LABEL}", INTEREST_IDS)
    print(f"  ── ad set {aset}（台灣 · 30-55 · 繁中 · 手動版位 · {W.BUDGET:.0f}/日）")

    name = N.ad_name("VID", 0, "課程導師·揭祕後台·全是AI做")
    ad = C.fb_retry(VP.create_video_ad, account, aset, vid, thumb, pt, hl, name)
    print(f"  ✓ 影片廣告 ad={ad}  {name}")
    print(f"→ 已建 1 支影片廣告（reeve style）於新 campaign（PAUSED）。")


if __name__ == "__main__":
    run()
