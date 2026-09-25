"""
只讀:列出一個 Drive 資料夾的結構(子資料夾 + 影片),往下兩層,方便看有哪些素材可用。
env: DRIVE_FOLDER_ID, GOOGLE_SA_JSON
用法: python list_drive_tree.py
"""
import os
import config as C
import video_pipeline as VP


def children(svc, fid):
    q = f"'{fid}' in parents and trashed=false"
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, fields="nextPageToken, files(id,name,mimeType)",
                             pageToken=tok, pageSize=200).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


def run():
    svc = VP.drive_service()
    root = os.environ.get("DRIVE_FOLDER_ID") or "1b5z9Djj_LR5BZKb501Upvomvffx5_Pqy"
    print(f"[tree] root {root}")
    kids = children(svc, root)
    folders = [k for k in kids if k["mimeType"] == "application/vnd.google-apps.folder"]
    files = [k for k in kids if k["mimeType"] != "application/vnd.google-apps.folder"]
    vids = [f for f in files if "video" in f["mimeType"]]
    print(f"根目錄:{len(folders)} 個子資料夾 · {len(files)} 個檔案(其中 {len(vids)} 支影片)")
    for f in files:
        tag = "🎬" if "video" in f["mimeType"] else "📄"
        print(f"  {tag} {f['name']}")
    for d in folders:
        sub = children(svc, d["id"])
        sv = [s for s in sub if "video" in s["mimeType"]]
        so = [s for s in sub if "video" not in s["mimeType"] and s["mimeType"] != "application/vnd.google-apps.folder"]
        sf = [s for s in sub if s["mimeType"] == "application/vnd.google-apps.folder"]
        print(f"\n📁 {d['name']}  (id {d['id']})  → {len(sv)} 影片 · {len(so)} 其他檔 · {len(sf)} 子資料夾")
        for s in sub:
            tag = "🎬" if "video" in s["mimeType"] else ("📁" if s["mimeType"].endswith("folder") else "📄")
            print(f"    {tag} {s['name']}")


if __name__ == "__main__":
    run()
