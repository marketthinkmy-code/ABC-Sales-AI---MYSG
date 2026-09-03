"""
只讀探勘『軟體使用數據』表的結構(給後續 買家×使用率 交叉用)。
只印:欄位名 · 列數 · 各『低基數欄位』的值分佈(行業/方案/狀態這種)。
高基數欄位(email/姓名/id)只印非空筆數,不印任何值 —— 不外洩個資。

env: GOOGLE_SA_JSON, USAGE_SHEET_ID, USAGE_GID(選填)
"""
import os, io, csv, json
from collections import Counter
from google.oauth2 import service_account
from googleapiclient.discovery import build

USAGE_ID = os.environ["USAGE_SHEET_ID"]
GID = os.environ.get("USAGE_GID") or ""
SCOPES = ["https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/spreadsheets.readonly"]


def load():
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    print("SA client_email(要把表分享給這個帳號才讀得到):", info.get("client_email"))
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    # 先試 Sheets API(可指定 gid 那個分頁)
    try:
        sh = build("sheets", "v4", credentials=creds)
        meta = sh.spreadsheets().get(spreadsheetId=USAGE_ID).execute()
        title = None
        for s in meta.get("sheets", []):
            p = s.get("properties", {})
            if GID and str(p.get("sheetId")) == GID:
                title = p.get("title")
        if not title:
            title = meta["sheets"][0]["properties"]["title"]
        print(f"用 Sheets API 讀分頁:「{title}」")
        vals = sh.spreadsheets().values().get(
            spreadsheetId=USAGE_ID, range=title).execute().get("values", [])
        return vals
    except Exception as e:
        print(f"Sheets API 失敗({str(e)[:120]}),改用 Drive CSV 匯出(只會拿到第一個分頁)")
    drive = build("drive", "v3", credentials=creds)
    raw = drive.files().export(fileId=USAGE_ID, mimeType="text/csv").execute()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return list(csv.reader(io.StringIO(text)))


def run():
    vals = load()
    if not vals:
        print("⚠️ 讀到 0 列。可能是沒分享給 SA,或分頁空的。")
        return
    # 找表頭:第一個「非空欄位數最多」的前幾列
    hdr_i = max(range(min(5, len(vals))), key=lambda i: sum(1 for c in vals[i] if c.strip()))
    hdr = vals[hdr_i]
    rows = vals[hdr_i + 1:]
    print(f"\n總列數 {len(vals)} · 表頭在第 {hdr_i+1} 列 · 資料 {len(rows)} 筆")
    print(f"欄位({len(hdr)}):")
    for j, name in enumerate(hdr):
        col = [r[j].strip() for r in rows if j < len(r) and r[j].strip()]
        nonempty = len(col)
        distinct = len(set(col))
        tag = ""
        low = distinct <= 25 and distinct > 0
        print(f"  [{j:>2}] {name[:26]:<26} 非空 {nonempty:>4} · 相異 {distinct:>4}"
              + ("  ← 分類欄" if low else ("  (高基數,略過值)" if distinct else "")))
        if low:
            dist = Counter(col).most_common(25)
            for v, c in dist:
                print(f"          {c:>4} × {v[:40]}")


if __name__ == "__main__":
    run()
