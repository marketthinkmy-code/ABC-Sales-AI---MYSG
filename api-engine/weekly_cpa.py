"""
每週 CPA 戰報引擎:
  讀「已付款學員」Sheet(Stripe 買單) → 拉 Meta 廣告花費/報名 → 依素材(UTM Ads Name)歸因
  → 算 CPL / CPA / ROAS + 判定(KILL·KEEP·SCALE) → 產生私密網頁看板(reports/cpa_report.html)。

兩個維度:
  - 總覽 Lifetime:歷史到現在,每支素材的累計買單/花費/CPA/ROAS。
  - 本週期 近7天:上一週的單場數據。

需要 env / Secret:
  GOOGLE_SA_JSON, META_ACCESS_TOKEN, AD_ACCOUNT_ID, BUYER_SHEET_ID(選填,有預設)
用法: python weekly_cpa.py
"""
import os, re, json, html, datetime as dt
import config as C
from facebook_business.adobjects.adaccount import AdAccount

PRICE = float(os.environ.get("PRICE_PER_SALE") or 39800)
ROAS_KEEP = float(os.environ.get("ROAS_KEEP") or 2.5)
ROAS_SCALE = float(os.environ.get("ROAS_SCALE") or 3.0)
KILL_CPL = float(getattr(C, "KILL_CPL", 290) or 290)
SHEET_ID = os.environ.get("BUYER_SHEET_ID") or "1WdNp5xFYlVg6TPSJC4u-ZwSGtni-R54Kr9b6ZvuQ4yo"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "reports")


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


# ---------- 1. 讀買單 Sheet ----------
def read_buyers():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    svc = build("sheets", "v4", credentials=creds)
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    title = meta["sheets"][0]["properties"]["title"]
    vals = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=title).execute().get("values", [])
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
    ci_pay, ci_src, ci_as, ci_an = col("付費管道"), col("source"), col("UTM Ads Set"), col("UTM Ads Name")
    ci_pt = col("付款時間")
    buyers = []
    for row in vals[hidx + 1:]:
        sidx = next((j for j, c in enumerate(row) if (c or "").strip().lower() == "stripe"), None)
        if sidx is None:
            continue
        shift = sidx - ci_pay

        def g(idx):
            j = idx + shift
            return norm(row[j]) if (idx is not None and 0 <= j < len(row)) else ""
        pt = g(ci_pt)
        d = None
        m = re.search(r"\d{4}-\d{2}-\d{2}", pt)
        if m:
            try:
                d = dt.date.fromisoformat(m.group(0))
            except ValueError:
                d = None
        buyers.append({"campaign": g(ci_src), "adset": g(ci_as),
                       "creative": g(ci_an), "date": d})
    return buyers


# ---------- 2. 拉 Meta 花費 / 報名 ----------
def _is_reg(action_type):
    a = action_type.lower()
    return ("complete_registration" in a or a == "lead"
            or a.endswith(".lead") or "registration" in a)


def meta_by_ad(preset):
    """回傳 {正規化 ad_name: {spend, leads}} 與 campaign/adset 彙總。"""
    acct = AdAccount(C.ACT_ID)
    by_ad, by_cp, by_as = {}, {}, {}
    params = {"level": "ad", "date_preset": preset, "limit": 500,
              "fields": ["ad_name", "adset_name", "campaign_name", "spend", "actions"]}
    try:
        rows = acct.get_insights(params=params)
    except Exception as e:
        print(f"  ⚠️ Meta insights({preset}) 讀取失敗: {e}")
        return by_ad, by_cp, by_as
    for r in rows:
        spend = float(r.get("spend", 0) or 0)
        leads = 0
        for a in (r.get("actions") or []):
            if _is_reg(a["action_type"]):
                leads += int(float(a["value"]))
        an = norm(r.get("ad_name", ""))
        cp = norm(r.get("campaign_name", ""))
        aset = norm(r.get("adset_name", ""))
        for key, d in ((an, by_ad), (cp, by_cp), (aset, by_as)):
            if not key:
                continue
            slot = d.setdefault(key, {"spend": 0.0, "leads": 0})
            slot["spend"] += spend
            slot["leads"] += leads
    return by_ad, by_cp, by_as


def match_spend(creative_label, by_ad):
    """把買單素材標籤(UTM Ads Name)對到 Meta ad_name 花費(完全或包含匹配)。"""
    lab = norm(creative_label)
    if lab in by_ad:
        return by_ad[lab]["spend"], by_ad[lab]["leads"]
    sp = ld = 0
    hit = False
    for name, d in by_ad.items():
        if lab and (lab in name or name in lab):
            sp += d["spend"]; ld += d["leads"]; hit = True
    return (sp, ld) if hit else (0.0, 0)


# ---------- 3. 判定 ----------
def verdict(buyers, spend, leads):
    cpl = (spend / leads) if leads else None
    if buyers == 0:
        if cpl is not None and cpl >= KILL_CPL:
            return "KILL", "新素材 CPL 破線"
        return "WATCH", "新素材觀察中"
    if not spend:
        return "DATA", "待花費數據"
    roas = (buyers * PRICE) / spend
    if roas >= ROAS_SCALE:
        return "SCALE", f"ROAS {roas:.1f} · 加預算"
    if roas >= ROAS_KEEP:
        return "KEEP", f"ROAS {roas:.1f} · 保留"
    return "KILL", f"ROAS {roas:.1f} · 低於 2.5"


# ---------- 4. 聚合 ----------
def build_rows(buyers, by_ad, window=None):
    from collections import defaultdict
    agg = defaultdict(lambda: {"buyers": 0, "pairs": defaultdict(int)})
    unattributed = 0
    for b in buyers:
        if window and (b["date"] is None or b["date"] < window):
            continue
        cr = b["creative"]
        if not cr:
            unattributed += 1
            continue
        agg[cr]["buyers"] += 1
        agg[cr]["pairs"][(b["campaign"] or "—", b["adset"] or "—")] += 1
    rows = []
    for cr, info in agg.items():
        spend, leads = match_spend(cr, by_ad)
        v, why = verdict(info["buyers"], spend, leads)
        top = max(info["pairs"].items(), key=lambda x: x[1])[0] if info["pairs"] else ("—", "—")
        rows.append({
            "name": cr, "buyers": info["buyers"], "revenue": info["buyers"] * PRICE,
            "spend": spend, "leads": leads,
            "cpl": (spend / leads) if leads else None,
            "cpa": (spend / info["buyers"]) if (spend and info["buyers"]) else None,
            "roas": ((info["buyers"] * PRICE) / spend) if spend else None,
            "campaign": top[0], "adset": top[1], "sources": len(info["pairs"]),
            "verdict": v, "why": why,
        })
    rows.sort(key=lambda r: (-r["buyers"], -(r["roas"] or 0)))
    return rows, unattributed


# ---------- 5. 產生 HTML ----------
def esc(s):
    return html.escape(str(s))


def money(n):
    return f"{n:,.0f}"


def short_cp(s):
    return (s or "—").replace("MTC - AI回覆幫你獲客 - ", "").strip() or "—"


def short_as(s):
    s = s or "—"
    return (s[:34] + "…") if len(s) > 35 else s


def render_table(rows):
    maxb = max((r["buyers"] for r in rows), default=1) or 1
    out = ""
    for r in rows:
        is_img = r["name"].lower().startswith("single image")
        nm = r["name"].replace("Single image: ", "")
        tag = '<span class="tag img">單圖</span>' if is_img else '<span class="tag vid">影片</span>'
        barw = round(r["buyers"] / maxb * 100)
        vcls = {"SCALE": "v-scale", "KEEP": "v-keep", "KILL": "v-kill",
                "WATCH": "v-watch", "DATA": "v-data"}[r["verdict"]]
        vlbl = {"SCALE": "加預算", "KEEP": "保留", "KILL": "關掉",
                "WATCH": "觀察", "DATA": "待數據"}[r["verdict"]]
        spend = money(r["spend"]) if r["spend"] else "—"
        cpa = money(r["cpa"]) if r["cpa"] else "—"
        roas = f'{r["roas"]:.2f}' if r["roas"] else "—"
        more = f'<span class="more">+{r["sources"]-1} 來源</span>' if r["sources"] > 1 else ""
        out += f"""<tr>
      <td class="cell-name">{tag}<span class="nm">{esc(nm)}</span></td>
      <td class="num"><div class="barwrap"><span class="barval">{r['buyers']}</span><span class="bar" style="width:{barw}%"></span></div></td>
      <td class="num money rev">{money(r['revenue'])}</td>
      <td class="num money">{spend}</td>
      <td class="num money">{cpa}</td>
      <td class="num">{roas}</td>
      <td><span class="vd {vcls}">{vlbl}</span></td>
      <td class="src">{esc(short_cp(r['campaign']))} {more}</td>
      <td class="src dim">{esc(short_as(r['adset']))}</td>
    </tr>"""
    return out


def render(life_rows, life_unattr, week_rows, buyers_total, window_str):
    tot_rev = buyers_total * PRICE
    attr = sum(r["buyers"] for r in life_rows)
    body = f"""<div class="wrap">
<header class="top">
  <div class="eyebrow">ABC SALES AI · 台灣 · 廣告買單戰報</div>
  <h1>素材買單戰報 <span class="cpa">CPA Dashboard</span></h1>
  <p class="sub">已付款學員 Sheet（Stripe 買單）· 客單價 <b>NT${money(PRICE)}</b> · 判定線 ROAS ≥ {ROAS_KEEP} 保留、≥ {ROAS_SCALE} 加預算 · 每週三 10:00 自動更新</p>
</header>
<section class="kpis">
  <div class="kpi"><div class="k-lbl">總買單</div><div class="k-val">{buyers_total}</div><div class="k-sub">Stripe 已付款</div></div>
  <div class="kpi good"><div class="k-lbl">總營收</div><div class="k-val">NT${money(tot_rev)}</div><div class="k-sub">{buyers_total} × {money(PRICE)}</div></div>
  <div class="kpi"><div class="k-lbl">可歸因</div><div class="k-val">{attr}<span class="k-of">/{buyers_total}</span></div><div class="k-sub">有 UTM 的買單</div></div>
  <div class="kpi warn"><div class="k-lbl">未歸因</div><div class="k-val">{life_unattr}</div><div class="k-sub">無 UTM · 另列</div></div>
</section>
<section class="card">
  <div class="card-hd"><h2>總覽 Lifetime · 每支素材</h2>
    <div class="legend"><span class="tag vid">影片</span><span class="tag img">單圖</span></div></div>
  <div class="tbl-scroll"><table>
    <thead><tr><th>廣告名</th><th class="num">買單</th><th class="num">營收</th><th class="num">花費</th>
      <th class="num">CPA</th><th class="num">ROAS</th><th>判定</th><th>來源 Campaign</th><th>來源 Ad Set</th></tr></thead>
    <tbody>{render_table(life_rows)}</tbody></table></div>
  <div class="note">CPA = 花費 ÷ 買單;ROAS = 營收 ÷ 花費。花費為 Meta 目前可查到的歷史數據;舊廣告若已刪除,花費可能不完整,之後每週累積會越來越準。</div>
</section>
<section class="card">
  <div class="card-hd"><h2>本週期 · 近 7 天（{window_str}）</h2></div>
  <div class="tbl-scroll"><table>
    <thead><tr><th>廣告名</th><th class="num">買單</th><th class="num">營收</th><th class="num">花費</th>
      <th class="num">CPA</th><th class="num">ROAS</th><th>判定</th><th>來源 Campaign</th><th>來源 Ad Set</th></tr></thead>
    <tbody>{render_table(week_rows) if week_rows else '<tr><td colspan="9" class="src dim">近 7 天暫無可歸因買單</td></tr>'}</tbody></table></div>
</section>
<footer class="ft">每週三 10:00 自動更新 · 未歸因買單＝當時沒帶 UTM,單獨計不混入素材成效</footer>
</div>"""
    tmpl = open(os.path.join(HERE, "report_template.html"), encoding="utf-8").read()
    return tmpl.replace("<!--BODY-->", body)


def run():
    C.init_api()
    buyers = read_buyers()
    print(f"[weekly] 讀到 {len(buyers)} 筆 Stripe 買單")
    life_ad, _, _ = meta_by_ad("maximum")
    week_ad, _, _ = meta_by_ad("last_7d")
    life_rows, life_unattr = build_rows(buyers, life_ad)
    window = dt.date.today() - dt.timedelta(days=7)
    week_rows, _ = build_rows(buyers, week_ad, window=window)
    window_str = f"{window.isoformat()} ~ {dt.date.today().isoformat()}"
    htmlout = render(life_rows, life_unattr, week_rows, len(buyers), window_str)
    os.makedirs(OUT_DIR, exist_ok=True)
    open(os.path.join(OUT_DIR, "cpa_report.html"), "w", encoding="utf-8").write(htmlout)
    open(os.path.join(OUT_DIR, "cpa_data.json"), "w", encoding="utf-8").write(
        json.dumps({"buyers_total": len(buyers), "unattributed": life_unattr,
                    "lifetime": life_rows}, ensure_ascii=False, indent=1))
    print(f"→ 已產生 reports/cpa_report.html（{len(life_rows)} 支素材）")


if __name__ == "__main__":
    run()
