"""
聚合 ZIV 房貸 funnel 的『付款學員』分頁 —— 只輸出 campaign / ad set / creative 的「成交人數」聚合,
不輸出任何個資(姓名/email/電話一律不印、不帶出)。

env: GOOGLE_SA_JSON, ZIV_SHEET_ID, ZIV_TAB(預設 付款學員), ZIV_RANGE(預設 A1:AE1200)
用法: python analyze_buyers_ziv.py
"""
import os, io, json, collections

SHEET_ID = os.environ["ZIV_SHEET_ID"]
TAB = os.environ.get("ZIV_TAB") or "付款學員"
RNG = os.environ.get("ZIV_RANGE") or "A1:AE1200"


def sheets():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def col(headers, *names):
    for i, h in enumerate(headers):
        hs = (h or "").strip().lower()
        for n in names:
            if hs == n.strip().lower():
                return i
    # 容錯:包含關係
    for i, h in enumerate(headers):
        hs = (h or "").strip().lower()
        for n in names:
            if n.strip().lower() in hs:
                return i
    return -1


def main():
    svc = sheets()
    try:
        vals = svc.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"'{TAB}'!{RNG}").execute().get("values", [])
    except Exception as e:
        msg = str(e)
        print(f"✗ 讀不到試算表: {msg[:200]}")
        if "403" in msg or "PERMISSION" in msg or "404" in msg:
            print("→ 把這份試算表分享(檢視權限)給服務帳號:\n   twabc-ads-bot@abctwai.iam.gserviceaccount.com")
        raise SystemExit(1)

    if not vals:
        raise SystemExit("分頁沒資料。")

    # 找 header 列(含 'source' 與 'UTM Ads Name')
    hrow = 0
    for i, r in enumerate(vals[:5]):
        low = [(c or "").strip().lower() for c in r]
        if any("source" == c for c in low) and any("utm ads name" in c for c in low):
            hrow = i
            break
    headers = vals[hrow]
    i_name = col(headers, "名字", "Name")
    i_pay = col(headers, "付費管道")
    i_ptime = col(headers, "付款時間")
    i_src = col(headers, "source")
    i_set = col(headers, "UTM Ads Set")
    i_ad = col(headers, "UTM Ads Name")
    print(f"分頁 {TAB} | header 在第 {hrow+1} 列 | 欄位 index: name={i_name} pay={i_pay} "
          f"ptime={i_ptime} source={i_src} adset={i_set} adname={i_ad}")

    def g(r, i):
        return (r[i].strip() if 0 <= i < len(r) and r[i] else "")

    total = refunds = attributed = 0
    by_ad = collections.Counter()
    by_src = collections.Counter()
    by_set = collections.Counter()
    by_ad_set = collections.Counter()  # creative × adset 交叉(選)
    for r in vals[hrow+1:]:
        name = g(r, i_name)
        if not name or name.lower() in ("name", "名字"):
            continue
        # 需要像一筆成交:有付費管道或付款時間
        if not (g(r, i_pay) or g(r, i_ptime)):
            continue
        rowtext = " ".join(c or "" for c in r)
        is_refund = "退款" in rowtext
        total += 1
        if is_refund:
            refunds += 1
            continue  # 退款不算有效成交
        src = g(r, i_src)
        aset = g(r, i_set)
        ad = g(r, i_ad)
        if src or ad or aset:
            attributed += 1
        by_ad[ad or "(空白/無標記)"] += 1
        by_src[src or "(空白/無標記)"] += 1
        by_set[(aset[:70] + "…") if len(aset) > 70 else (aset or "(空白)")] += 1

    net = total - refunds
    print(f"\n==== 總覽 ====")
    print(f"付款列總數: {total} | 退款: {refunds} | 淨成交: {net} | 有廣告標記: {attributed} "
          f"({attributed/net*100:.0f}% of 淨成交)" if net else "")

    def dump(title, counter, topn=30):
        print(f"\n==== {title}（淨成交 {net}）====")
        for k, c in counter.most_common(topn):
            print(f"  {c:>4}  ({c/net*100:4.1f}%)  {k}")

    dump("A. 成交來自哪支 creative（UTM Ads Name）", by_ad)
    dump("B. 成交來自哪個 campaign（source）", by_src)
    dump("C. 成交來自哪個 ad set（UTM Ads Set，截斷顯示）", by_set, topn=25)


if __name__ == "__main__":
    main()
