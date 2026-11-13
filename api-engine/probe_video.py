"""
下載 Drive 影片 → 用 ffmpeg 抽出等間隔的畫格(含燒進去的字幕),存成 jpg。
給「看影片內容 → 寫文案」用。不建任何廣告。

支援兩種:
- PROBE_FILE_ID: 單一檔案 → scratch/video_probe/
- PROBE_FOLDER_ID: 整個資料夾的所有影片 → scratch/video_probe/<檔名>/

env: GOOGLE_SA_JSON, PROBE_FILE_ID 或 PROBE_FOLDER_ID, PROBE_FRAMES(預設 12)
"""
import os, io, re, json, subprocess, shutil

FILE_ID = os.environ.get("PROBE_FILE_ID") or ""
FOLDER_ID = os.environ.get("PROBE_FOLDER_ID") or ""
FRAMES = int(os.environ.get("PROBE_FRAMES") or 12)
ROOT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", "video_probe")
SA_EMAIL = "twabc-ads-bot@abctwai.iam.gserviceaccount.com"


def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download(svc, fid, path):
    from googleapiclient.http import MediaIoBaseDownload
    req = svc.files().get_media(fileId=fid, supportsAllDrives=True)
    with io.FileIO(path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=16 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def list_videos(svc, folder):
    out, tok = [], None
    while True:
        resp = svc.files().list(
            q=f"'{folder}' in parents and trashed=false and mimeType contains 'video/'",
            fields="nextPageToken, files(id,name,size)", pageSize=200,
            supportsAllDrives=True, includeItemsFromAllDrives=True, pageToken=tok).execute()
        out += resp.get("files", [])
        tok = resp.get("nextPageToken")
        if not tok:
            break
    return out


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.splitext(name)[0])[:40]


def probe_one(svc, fid, name, outdir):
    os.makedirs(outdir, exist_ok=True)
    src = os.path.join(outdir, "_src.mp4")
    download(svc, fid, src)
    dur = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", src]).decode().strip() or "0")
    n = max(1, FRAMES)
    step = max(dur / (n + 1), 0.5)
    got = 0
    for i in range(1, n + 1):
        t = step * i
        if t >= dur:
            break
        out = os.path.join(outdir, f"f{i:02d}_{t:05.1f}s.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", src,
                        "-frames:v", "1", "-vf", "scale=540:-1", "-q:v", "4", out], check=False)
        got += 1
    os.remove(src)
    print(f"  ✓ {name} | {dur:.0f}s | 抽 {got} 格 → {outdir}")


def main():
    svc = drive_service()
    if os.path.isdir(ROOT_OUT):
        shutil.rmtree(ROOT_OUT)
    os.makedirs(ROOT_OUT, exist_ok=True)

    if FOLDER_ID:
        vids = list_videos(svc, FOLDER_ID)
        print(f"資料夾 {FOLDER_ID}: {len(vids)} 支影片")
        if not vids:
            print(f"→ 資料夾空或沒分享給 SA。請分享給 {SA_EMAIL}(檢視)。")
            raise SystemExit(1)
        for v in vids:
            try:
                probe_one(svc, v["id"], v["name"], os.path.join(ROOT_OUT, safe(v["name"])))
            except Exception as e:
                print(f"  ⚠️ {v['name']} 失敗: {str(e)[:120]}")
    elif FILE_ID:
        meta = svc.files().get(fileId=FILE_ID, fields="name", supportsAllDrives=True).execute()
        probe_one(svc, FILE_ID, meta["name"], ROOT_OUT)
    else:
        raise SystemExit("給 PROBE_FILE_ID 或 PROBE_FOLDER_ID。")


if __name__ == "__main__":
    main()
