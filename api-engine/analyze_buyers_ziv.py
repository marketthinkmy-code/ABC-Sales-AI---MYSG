"""
聚合 MTC funnel 的『付款學員』分頁 —— 只輸出 campaign / ad set / creative 的「成交人數」聚合,
不輸出任何個資(姓名/email/電話一律不印、不帶出)。

走 Drive export(SA 的 drive.readonly 權限)把整本匯出成 xlsx 再用 openpyxl 解析指定分頁,
避免 Sheets API(專案層級可能沒開)。

env: GOOGLE_SA_JSON, ZIV_SHEET_ID, ZIV_TAB(預設 付款學員), DRY_RUN(無作用)
用法: ZIV_SHEET_ID=xxx python analyze_buyers_ziv.py
"""
import os, io, json, collections

SHEET_ID = os.environ["ZIV_SHEET_ID"]
TAB = (os.environ.get("ZIV_TAB") or "付款學員").strip()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def export_xlsx(fid, path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    req = svc.files().export_media(fileId=fid, mimeType=XLSX)
    with io.FileIO(path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def pick_sheet(wb, want):
    for ws in wb.worksheets:
        if (ws.title or "").strip() == want:
            return ws
    for ws in wb.worksheets:
        if want in (ws.title or ""):
            return ws
    return None


def col(headers, *names):
    low = [(h or "").strip().lower() for h in headers]
    for n in names:
        for i, h in enumerate(low):
            if h == n.strip().lower():
                return i
    for n in names:
        for i, h in enumerate(low):
            if n.strip().lower() in h:
                return i
    return -1


def main():
    import openpyxl
    path = "/tmp/book.xlsx"
    print(f"匯出試算表 {SHEET_ID} …")
    try:
        export_xlsx(SHEET_ID, path)
    except Exception as e:
        print(f"✗ 匯出失敗: {str(e)[:200]}")
        raise SystemExit(1)
    print(f"✓ 匯出 {os.path.getsize(path)} bytes，載入…")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    print(f"  分頁清單: {[w.title for w in wb.worksheets]}")
    ws = pick_sheet(wb, TAB)
    if ws is None:
        raise SystemExit(f"找不到分頁『{TAB}』。")
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    print(f"  分頁『{ws.title}』: {len(rows)} 列")

    # 找 header 列
    hrow = 0
    for i, r in enumerate(rows[:6]):
        low = [str(c).strip().lower() if c is not None else "" for c in r]
        if any(c == "source" for c in low) and any("utm ads name" in c for c in low):
            hrow = i
            break
    headers = [str(c) if c is not None else "" for c in rows[hrow]]
    i_name = col(headers, "名字", "Name")
    i_pay = col(headers, "付費管道")
    i_ptime = col(headers, "付款時間")
    i_src = col(headers, "source")
    i_set = col(headers, "UTM Ads Set")
    i_ad = col(headers, "UTM Ads Name")
    print(f"  header 第 {hrow+1} 列 | index: name={i_name} pay={i_pay} ptime={i_ptime} "
          f"source={i_src} adset={i_set} adname={i_ad}")
    if i_ad < 0 and i_src < 0:
        raise SystemExit("找不到 source / UTM Ads Name 欄,請確認分頁。")

    def g(r, i):
        if 0 <= i < len(r) and r[i] is not None:
            return str(r[i]).strip()
        return ""

    total = refunds = attributed = 0
    by_ad = collections.Counter()
    by_src = collections.Counter()
    by_set = collections.Counter()
    for r in rows[hrow+1:]:
        name = g(r, i_name)
        if not name or name.lower() in ("name", "名字"):
            continue
        if not (g(r, i_pay) or g(r, i_ptime)):
            continue
        rowtext = " ".join(str(c) for c in r if c is not None)
        total += 1
        if "退款" in rowtext:
            refunds += 1
            continue
        src, aset, ad = g(r, i_src), g(r, i_set), g(r, i_ad)
        if src or ad or aset:
            attributed += 1
        by_ad[ad or "(空白/無標記)"] += 1
        by_src[src or "(空白/無標記)"] += 1
        by_set[(aset[:70] + "…") if len(aset) > 70 else (aset or "(空白)")] += 1

    net = total - refunds
    print(f"\n==== 總覽 ====")
    print(f"付款列總數: {total} | 退款: {refunds} | 淨成交: {net} | 有廣告標記: {attributed}"
          + (f" ({attributed/net*100:.0f}% of 淨成交)" if net else ""))
    if not net:
        return

    def dump(title, counter, topn=30):
        print(f"\n==== {title}（淨成交 {net}）====")
        for k, c in counter.most_common(topn):
            print(f"  {c:>4}  ({c/net*100:4.1f}%)  {k}")

    dump("A. 成交來自哪支 creative（UTM Ads Name）", by_ad)
    dump("B. 成交來自哪個 campaign（source）", by_src)
    dump("C. 成交來自哪個 ad set（UTM Ads Set，截斷顯示）", by_set, topn=25)


if __name__ == "__main__":
    main()
