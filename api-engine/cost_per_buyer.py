"""
每個 campaign 的「每買家成本 (cost-per-buyer)」：
- 從付款學員表(Drive export)數每個 source(campaign 名)帶幾個買家(不印個資)。
- 從 Meta(SDK insights, all-time)抓每個 campaign 的花費。
- 以 campaign 名配對,算 花費 ÷ 買家 = 每買家成本。

env: GOOGLE_SA_JSON, META_ACCESS_TOKEN, AD_ACCOUNT_ID, CPB_SHEET_ID, CPB_TAB(預設 付款學員)
用法: CPB_SHEET_ID=xxx python cost_per_buyer.py
"""
import os, io, json, collections, re
import config as C
from facebook_business.adobjects.adaccount import AdAccount

SHEET_ID = os.environ["CPB_SHEET_ID"]
TAB = (os.environ.get("CPB_TAB") or "付款學員").strip()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# 這些 source 不是付費廣告 campaign,不算 cost-per-buyer
NON_AD = {"", "social media", "direct traffic - invitation", "unidentified ad",
          "paid", "(空白/無標記)"}


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


def norm(s):
    return re.sub(r"\s+", "", (s or "").strip().lower())


def buyer_counts():
    import openpyxl
    path = "/tmp/book.xlsx"
    export_xlsx(SHEET_ID, path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = next((w for w in wb.worksheets if (w.title or "").strip() == TAB), None) \
        or next((w for w in wb.worksheets if TAB in (w.title or "")), None)
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    hrow = 0
    for i, r in enumerate(rows[:6]):
        low = [str(c).strip().lower() if c is not None else "" for c in r]
        if any(c == "source" for c in low) and any("utm ads name" in c for c in low):
            hrow = i
            break
    headers = [str(c).strip().lower() if c is not None else "" for c in rows[hrow]]
    i_name = next((i for i, h in enumerate(headers) if h in ("名字", "name")), 1)
    i_pay = next((i for i, h in enumerate(headers) if h == "付費管道"), 2)
    i_pt = next((i for i, h in enumerate(headers) if h == "付款時間"), 6)
    i_src = next((i for i, h in enumerate(headers) if h == "source"), 12)

    def g(r, i):
        return str(r[i]).strip() if 0 <= i < len(r) and r[i] is not None else ""
    cnt = collections.Counter()
    net = 0
    for r in rows[hrow+1:]:
        nm = g(r, i_name)
        if not nm or nm.lower() in ("name", "名字"):
            continue
        if not (g(r, i_pay) or g(r, i_pt)):
            continue
        if "退款" in " ".join(str(c) for c in r if c is not None):
            continue
        net += 1
        cnt[g(r, i_src) or "(空白/無標記)"] += 1
    return cnt, net


def campaign_spend():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    spend = {}
    rows = C.fb_retry(lambda: list(account.get_insights(
        fields=["campaign_name", "spend"],
        params={"level": "campaign", "date_preset": "maximum", "limit": 500})))
    for r in rows:
        nm = r.get("campaign_name")
        if nm:
            spend[nm] = spend.get(nm, 0.0) + float(r.get("spend") or 0)
    return spend


def match_spend(src, spend_map, norm_map):
    if src in spend_map:
        return spend_map[src], src
    ns = norm(src)
    if ns in norm_map:
        k = norm_map[ns]
        return spend_map[k], k
    # 子字串雙向
    for k in spend_map:
        nk = norm(k)
        if ns and (ns in nk or nk in ns):
            return spend_map[k], k
    return None, None


def main():
    cnt, net = buyer_counts()
    print(f"付款學員淨成交: {net} | 不重複 source: {len(cnt)}")
    spend_map = campaign_spend()
    print(f"Meta 抓到 {len(spend_map)} 個 campaign 的花費(all-time)\n")
    norm_map = {norm(k): k for k in spend_map}

    rows = []
    unmatched = []
    for src, buyers in cnt.most_common():
        if src.strip().lower() in NON_AD:
            continue
        sp, mk = match_spend(src, spend_map, norm_map)
        if sp is None:
            unmatched.append((src, buyers))
            continue
        cpb = sp / buyers if buyers else None
        rows.append({"src": src, "buyers": buyers, "spend": sp, "cpb": cpb, "matched": mk})

    rows.sort(key=lambda x: (x["cpb"] is None, x["cpb"]))
    print("==== 每買家成本(cost-per-buyer)· 由低到高 ====")
    print(f"{'買家':>4} {'花費TWD':>12} {'每買家':>10}  campaign(source)")
    for r in rows:
        print(f"{r['buyers']:>4} {r['spend']:>12,.0f} {r['cpb']:>10,.0f}  {r['src'][:46]}")

    tot_b = sum(r["buyers"] for r in rows)
    tot_s = sum(r["spend"] for r in rows)
    if tot_b:
        print(f"\n配對到花費的: {tot_b} 位買家 · 花費 {tot_s:,.0f} · 整體每買家 {tot_s/tot_b:,.0f} TWD")
    if unmatched:
        print(f"\n(配不到花費的 source — 多半是舊/已刪 campaign 或非付費來源)")
        for s, b in unmatched:
            print(f"   {b:>3}  {s[:50]}")


if __name__ == "__main__":
    main()
