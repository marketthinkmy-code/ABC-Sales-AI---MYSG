"""
『買家從哪來』分析:只從 Stripe 買單 Sheet 的 UTM 歸因,算出這幾十位真正付錢的人
來自哪支廣告 / 哪個受眾 / 哪個鉤子(hook),再對回 Meta 花費算每個來源的 CPA/ROAS。
只輸出彙總數字與百分比,絕不印任何個資(姓名/email/電話)。

env: GOOGLE_SA_JSON, META_ACCESS_TOKEN, AD_ACCOUNT_ID, PRICE_PER_SALE(預設 39800)
"""
import os, re
from collections import defaultdict
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from spend_audit import read_buyers, norm, _is_reg

PRICE = float(os.environ.get("PRICE_PER_SALE") or 39800)


def meta_by_ad(account):
    """帳號歷史(maximum)每支廣告的花費+報名,key=正規化廣告名。"""
    out = {}
    try:
        ins = C.fb_retry(account.get_insights,
                         params={"level": "ad", "date_preset": "maximum", "limit": 2000},
                         fields=["ad_name", "spend", "actions"])
    except Exception as e:
        print(f"  ⚠️ 讀 Meta 廣告花費失敗: {str(e)[:80]}")
        return out
    for r in ins:
        nm = norm(r.get("ad_name", ""))
        if not nm:
            continue
        spend = float(r.get("spend", 0) or 0)
        reg = 0
        for a in (r.get("actions") or []):
            if _is_reg(a["action_type"]):
                reg += int(float(a["value"]))
        slot = out.setdefault(nm, {"spend": 0.0, "reg": 0})
        slot["spend"] += spend
        slot["reg"] += reg
    return out


def match_spend(name, m):
    key = norm(name)
    if key in m:
        return m[key]
    for k, v in m.items():           # 退而求其次:子字串對上
        if k and key and (k in key or key in k):
            return v
    return None


def hook_of(name):
    """從廣告名抽出『鉤子/角度』——取最後一段(| 之後)或全形冒號前。"""
    n = norm(name)
    if "|" in n:
        n = n.split("|")[-1].strip()
    if "：" in n:
        n = n.split("：")[-1].strip() if n.startswith("M1Video") else n.split("：")[0].strip()
    return n[:28] or "(未命名)"


def winner_of(name):
    m = re.search(r"M1Video\s*\d+", name or "")
    return m.group(0).replace(" ", "") if m else None


def pct(a, b):
    return f"{(a / b * 100):.0f}%" if b else "—"


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    buyers = read_buyers()
    tot = len(buyers)
    dates = [b["date"] for b in buyers if b["date"]]
    dmin = min(dates).isoformat() if dates else "?"
    dmax = max(dates).isoformat() if dates else "?"
    m = meta_by_ad(account)

    by_ad = defaultdict(int)
    by_adset = defaultdict(int)
    by_src = defaultdict(int)
    by_hook = defaultdict(int)
    by_winner = defaultdict(int)
    tracked = 0
    for b in buyers:
        ad = b["creative"] or ""
        if ad:
            tracked += 1
        by_ad[ad or "(空白·未追蹤到廣告)"] += 1
        by_adset[b["adset"] or "(空白)"] += 1
        by_src[b["campaign"] or "(空白)"] += 1
        by_hook[hook_of(ad) if ad else "(空白)"] += 1
        w = winner_of(ad)
        if w:
            by_winner[w] += 1

    print("\n========== 買家來源分析(只算付錢的人) ==========")
    print(f"買家總數 {tot} 位 · 期間 {dmin} ~ {dmax} · 有追蹤到廣告 {tracked}/{tot}({pct(tracked, tot)})")

    def table(title, d, topn=15, withspend=False):
        print(f"\n[{title}]")
        rows = sorted(d.items(), key=lambda x: -x[1])[:topn]
        if withspend:
            print(f"  {'買家':>4} {'佔比':>5} {'花費':>8} {'CPA':>7} {'ROAS':>5}  來源")
            for name, cnt in rows:
                sm = match_spend(name, m) if not name.startswith("(") else None
                sp = sm["spend"] if sm else None
                cpa = sp / cnt if sp else None
                roas = (cnt * PRICE / sp) if sp else None
                print(f"  {cnt:>4} {pct(cnt, tot):>5} "
                      f"{(f'{sp:.0f}' if sp else '—'):>8} {(f'{cpa:.0f}' if cpa else '—'):>7} "
                      f"{(f'{roas:.1f}' if roas else '—'):>5}  {name[:46]}")
        else:
            print(f"  {'買家':>4} {'佔比':>5}  來源")
            for name, cnt in rows:
                print(f"  {cnt:>4} {pct(cnt, tot):>5}  {name[:52]}")

    table("A. 每支廣告帶來幾位買家(＋花費/CPA/ROAS)", by_ad, 15, withspend=True)
    table("B. 每個受眾(UTM Ads Set)帶來幾位買家", by_adset, 12)
    table("C. 每個流量來源(source)帶來幾位買家", by_src, 10)
    table("D. 每個鉤子/角度(hook)帶來幾位買家", by_hook, 15)
    if by_winner:
        table("E. 哪支贏家影片帶來幾位買家", by_winner, 12)

    # 整體:買家歸因到的廣告的花費合計 → 綜合 CPA/ROAS
    tot_spend = 0.0
    matched_buyers = 0
    for name, cnt in by_ad.items():
        if name.startswith("("):
            continue
        sm = match_spend(name, m)
        if sm:
            tot_spend += sm["spend"]
            matched_buyers += cnt
    print("\n[整體]")
    if tot_spend:
        print(f"  對得上花費的買家 {matched_buyers} 位 · 這些廣告合計花費 {tot_spend:.0f} TWD")
        print(f"  綜合 CPA ≈ {tot_spend / matched_buyers:.0f} TWD/位 · "
              f"綜合 ROAS ≈ {matched_buyers * PRICE / tot_spend:.1f}(客單價 {PRICE:.0f})")
    print("========== END ==========")


if __name__ == "__main__":
    run()
