"""
下載一支 Drive 影片 → 用 ffmpeg 抽出等間隔的畫格(含燒進去的字幕),存成 jpg。
給「看影片內容 → 寫文案」用。不建任何廣告。

env: GOOGLE_SA_JSON, PROBE_FILE_ID, PROBE_FRAMES(預設 24), PROBE_OUT(預設 scratch/video_probe)
用法: PROBE_FILE_ID=xxxx python probe_video.py
"""
import os, io, json, subprocess, shutil

FILE_ID = os.environ["PROBE_FILE_ID"]
FRAMES = int(os.environ.get("PROBE_FRAMES") or 24)
OUT = os.environ.get("PROBE_OUT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", "video_probe")
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
        dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def main():
    svc = drive_service()
    try:
        meta = svc.files().get(fileId=FILE_ID, fields="name,mimeType,size",
                               supportsAllDrives=True).execute()
    except Exception as e:
        msg = str(e)
        print(f"✗ 讀不到檔案: {msg[:200]}")
        if "404" in msg or "notFound" in msg or "403" in msg:
            print(f"→ 這支影片沒有分享給服務帳號。請把檔案(或它所在的資料夾)分享給:\n   {SA_EMAIL}（檢視權限即可)")
        raise SystemExit(1)
    print(f"檔名: {meta.get('name')} | {meta.get('mimeType')} | {meta.get('size')} bytes")

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    src = os.path.join(OUT, "_src.mov")
    print("下載中…")
    download(svc, FILE_ID, src)
    print(f"✓ 下載完成 {os.path.getsize(src)} bytes")

    # 時長
    dur = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", src]).decode().strip() or "0")
    print(f"時長: {dur:.1f}s")

    # 等間隔抽 FRAMES 格,縮到寬 540,jpg
    n = max(1, FRAMES)
    step = max(dur / (n + 1), 0.5)
    for i in range(1, n + 1):
        t = step * i
        if t >= dur:
            break
        out = os.path.join(OUT, f"f{i:02d}_{t:05.1f}s.jpg")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", src,
            "-frames:v", "1", "-vf", "scale=540:-1", "-q:v", "4", out], check=False)
    os.remove(src)
    got = sorted(f for f in os.listdir(OUT) if f.endswith(".jpg"))
    print(f"✓ 抽出 {len(got)} 格 → {OUT}")
    for f in got:
        print("   " + f)


if __name__ == "__main__":
    main()
