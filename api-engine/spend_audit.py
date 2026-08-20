"""
近 N 天『每支有花費的廣告』完整體檢：
  花費 · 報名(leads) · CPL · 成交(Stripe買單) · 成交率 · CPA · ROAS · 判定
並算出：預算浪費在哪（花在 0 成交 / 低 ROAS 的錢）。

- 廣告花費/報名：Meta ad-level insights（自訂 time_range 近 N 天）。
- 成交：買單 Sheet（Stripe），依 UTM Ads Name 對回廣告。
- 日期欄自動偵測（修掉舊版只認 ISO 格式、近 60 天全算 0 的 bug）。
- 只輸出彙總數字,不印任何個資。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, GOOGLE_SA_JSON, BUYER_SHEET_ID(選填),
     PRICE_PER_SALE(選填 39800), RECENT_DAYS(選填 60)
"""
import os, re, io, csv, json, datetime as dt
from collections import defaultdict
import config as C
from facebook_business.adobjects.adaccount import AdAccount

SHEET_ID = os.environ.get("BUYER_SHEET_ID") or "1WdNp5xFYlVg6TPSJC4u-ZwSGtni-R54Kr9b6ZvuQ4yo"
PRICE = float(os.environ.get("PRICE_PER_SALE") or 39800)
N = int(os.environ.get("RECENT_DAYS") or 60)
ROAS_SCALE, ROAS_KEEP = 3.0, 2.5


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)      # YYYY-M-D
    if m:
        y, mo, dd = map(int, m.groups())
        try:
            return dt.date(y, mo, dd)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", s)  # D/M/Y 或 M/D/Y
    if m:
        a, b, y = map(int, m.groups())
        for dd, mo in ((a, b), (b, a)):                            # 先當 D/M/Y,不合法再換
            try:
                return dt.date(y, mo, dd)
            except ValueError:
                pass
    return None


def read_buyers():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    drive = build("drive", "v3", credentials=creds)
    raw = drive.files().export(fileId=SHEET_ID, mimeType="text/csv").execute()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    vals = list(csv.reader(io.StringIO(text)))
    hdr = hidx = None
    for i, row in enumerate(vals):
        joined = " ".join(c or "" for c in row)
        if "電郵地址" in joined and "UTM Ads Name" in joined:
            hdr, hidx = row, i
            break
    if hdr is None:
        raise SystemExit("找不到表頭(電郵地址 / UTM Ads Name)")

    def col(n):
        for j, c in enumerate(hdr):
            if n in (c or ""):
                return j
        return None
    ci_pay, ci_an = col("付費管道"), col("UTM Ads Name")
    # stripe 資料列(用 shift 對齊欄位)
    rows = []
    for row in vals[hidx + 1:]:
        sidx = next((j for j, c in enumerate(row) if (c or "").strip().lower() == "stripe"), None)
        if sidx is None or ci_pay is None:
            continue
        shift = sidx - ci_pay
        rows.append((row, shift))
    # 自動偵測日期欄：對所有欄位算「能 parse 成日期的比率」,挑最高
    ncol = len(hdr)
    best_j, best_rate = None, 0.0
    for j in range(ncol):
        ok = tot = 0
        for row, shift in rows:
            k = j + shift
            if 0 <= k < len(row):
                tot += 1
                if parse_date(row[k]):
                    ok += 1
        rate = ok / tot if tot else 0
        # 排除 UTM Ads Name 這種可能含數字的欄:優先 header 有時間/日期字樣的
        hint = any(w in (hdr[j] or "") for w in ("時間", "日期", "Date", "date", "Time", "time"))
        score = rate + (0.5 if hint else 0)
        if score > best_rate:
            best_rate, best_j = score, j
    date_col_name = hdr[best_j] if best_j is not None else "(未找到)"
    buyers = []
    for row, shift in rows:
        def g(idx):
            k = idx + shift
            return norm(row[k]) if (idx is not None and 0 <= k < len(row)) else ""
        d = None
        if best_j is not None:
            k = best_j + shift
            if 0 <= k < len(row):
                d = parse_date(row[k])
        buyers.append({"creative": g(ci_an), "date": d})
    parsed = sum(1 for b in buyers if b["date"])
    print(f"[audit] 買單 {len(buyers)} 筆 · 日期欄=「{date_col_name}」· 成功讀到日期 {parsed}/{len(buyers)}")
    return buyers


def _is_reg(a):
    a = a.lower()
    return "complete_registration" in a or a == "lead" or a.endswith(".lead") or "registration" in a


def meta_ads(time_range):
    acct = AdAccount(C.ACT_ID)
    out = {}
    params = {"level": "ad", "time_range": time_range, "limit": 500,
              "fields": ["ad_name", "campaign_name", "spend", "actions"]}
    for r in acct.get_insights(params=params):
        spend = float(r.get("spend", 0) or 0)
        leads = 0
        for a in (r.get("actions") or []):
            if _is_reg(a["action_type"]):
                leads += int(float(a["value"]))
        key = norm(r.get("ad_name", ""))
        if not key:
            continue
        slot = out.setdefault(key, {"spend": 0.0, "leads": 0, "campaign": norm(r.get("campaign_name", ""))})
        slot["spend"] += spend
        slot["leads"] += leads
    return out


def match_buyer_to_ad(creative, ad_names):
    """把一筆買單(UTM Ads Name)對到最合適的一支廣告名(唯一,取最長相符)。"""
    lab = norm(creative)
    if not lab:
        return None
    if lab in ad_names:
        return lab
    best = None
    for name in ad_names:
        if lab in name or name in lab:
            if best is None or len(name) > len(best):
                best = name
    return best


def run():
    C.init_api()
    today = dt.date.today()
    since = today - dt.timedelta(days=N)
    tr = {"since": since.isoformat(), "until": today.isoformat()}
    buyers = read_buyers()
    ads = meta_ads(tr)
    ad_names = set(ads.keys())

    # 視窗內買單 → 對到廣告
    win_buyers = [b for b in buyers if b["date"] and b["date"] >= since]
    buyers_by_ad = defaultdict(int)
    unmatched = 0
    for b in win_buyers:
        m = match_buyer_to_ad(b["creative"], ad_names)
        if m:
            buyers_by_ad[m] += 1
        else:
            unmatched += 1

    rows = []
    for name, d in ads.items():
        sp = d["spend"]
        if sp <= 0:
            continue
        leads = d["leads"]
        bz = buyers_by_ad.get(name, 0)
        rev = bz * PRICE
        cpl = sp / leads if leads else None
        cpa = sp / bz if bz else None
        roas = rev / sp if sp else None
        close = (bz / leads) if leads else None         # 成交率 = 買單 / 報名
        if bz == 0:
            v = "無成交"
        elif roas >= ROAS_SCALE:
            v = "SCALE 加預算"
        elif roas >= ROAS_KEEP:
            v = "KEEP 保留"
        else:
            v = "KILL 低ROAS"
        rows.append({"name": name, "campaign": d["campaign"], "spend": sp, "leads": leads,
                     "cpl": cpl, "buyers": bz, "close": close, "cpa": cpa, "roas": roas, "v": v})

    tot_spend = sum(r["spend"] for r in rows)
    tot_leads = sum(r["leads"] for r in rows)
    tot_buyers = sum(r["buyers"] for r in rows)
    waste = sum(r["spend"] for r in rows if r["buyers"] == 0)
    lowroas = sum(r["spend"] for r in rows if r["buyers"] > 0 and r["roas"] and r["roas"] < ROAS_KEEP)
    good = sum(r["spend"] for r in rows if r["roas"] and r["roas"] >= ROAS_KEEP)

    def m(n):
        return f"{n:,.0f}"

    print("AUDIT_START")
    print(f"視窗：近 {N} 天（{since} ~ {today}）")
    print(f"有花費的廣告={len(rows)} 支 · 總花費={m(tot_spend)} · 總報名={tot_leads} · 對到的成交={tot_buyers}（未對到 {unmatched}）")
    print(f"整體：CPL={m(tot_spend/tot_leads) if tot_leads else '—'} · CPA={m(tot_spend/tot_buyers) if tot_buyers else '—'} · 報名→成交率={ (tot_buyers/tot_leads*100) if tot_leads else 0:.1f}%")
    print()
    print("== 預算去向（錢花在哪）==")
    print(f"  🔴 花在『0 成交』廣告：{m(waste)}（{waste/tot_spend*100 if tot_spend else 0:.0f}%）")
    print(f"  🟠 花在『有成交但 ROAS<2.5』：{m(lowroas)}（{lowroas/tot_spend*100 if tot_spend else 0:.0f}%）")
    print(f"  🟢 花在『ROAS≥2.5』：{m(good)}（{good/tot_spend*100 if tot_spend else 0:.0f}%）")
    print()
    print("== 每支有花費的廣告（依花費高→低）==")
    print(f"{'廣告':40s} {'花費':>8s} {'報名':>4s} {'CPL':>6s} {'成交':>4s} {'成交率':>6s} {'CPA':>7s} {'ROAS':>5s}  判定")
    for r in sorted(rows, key=lambda x: -x["spend"]):
        print(f"{(r['name'] or '')[:38]:40s} {r['spend']:8,.0f} {r['leads']:4d} "
              f"{m(r['cpl']) if r['cpl'] else '—':>6s} {r['buyers']:4d} "
              f"{(('%.1f%%'%(r['close']*100)) if r['close'] is not None else '—'):>6s} "
              f"{m(r['cpa']) if r['cpa'] else '—':>7s} {('%.2f'%r['roas']) if r['roas'] else '—':>5s}  {r['v']}")
    print()
    print("== 🔴 燒最多、卻 0 成交（最該先砍）==")
    for r in sorted([r for r in rows if r["buyers"] == 0], key=lambda x: -x["spend"])[:10]:
        print(f"  {(r['name'] or '')[:40]:42s} 花費 {m(r['spend'])} · 報名 {r['leads']} · CPL {m(r['cpl']) if r['cpl'] else '—'}")
    print()
    print("== 🟢 有成交、ROAS 好（該加預算）==")
    for r in sorted([r for r in rows if r["roas"] and r["roas"] >= ROAS_SCALE], key=lambda x: -x["roas"]):
        print(f"  {(r['name'] or '')[:40]:42s} 花費 {m(r['spend'])} · 成交 {r['buyers']} · ROAS {r['roas']:.2f}")
    print("AUDIT_END")


if __name__ == "__main__":
    run()
