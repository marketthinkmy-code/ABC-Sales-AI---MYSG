"""
全帳號廣告掃描 —— 找「以前沒投多少錢、但有潛力」的舊廣告拿來重跑(對抗素材疲勞)。

- Query A(date_preset=maximum):每支廣告『歷史』花費 / 曝光 / 報名 / CPL(依 ad_name 聚合)。
- Query B(last_14d):每支廣告近 14 天 frequency,標出疲勞(頻率高)的主力。
輸出:
  1) 低花費潛力股:歷史花費不高、但有報名且 CPL 不錯 → 值得加碼/重跑。
  2) 幾乎沒投過:歷史花費 < MIN_SPENT → 根本沒被好好測過,可以挑來試。
  3) 近 14 天疲勞:frequency 高的主力 → 該換素材/補新角度。
只輸出彙總,不印個資。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID,
     MIN_SPENT(預設 100), POTENTIAL_MAX_SPENT(預設 1500),
     GOOD_CPL(預設 90), MIN_LEADS(預設 5), FATIGUE_FREQ(預設 2.5)
"""
import os
from collections import defaultdict
import config as C
from facebook_business.adobjects.adaccount import AdAccount

MIN_SPENT = float(os.environ.get("MIN_SPENT") or 100)
POT_MAX = float(os.environ.get("POTENTIAL_MAX_SPENT") or 1500)
GOOD_CPL = float(os.environ.get("GOOD_CPL") or 90)
MIN_LEADS = int(os.environ.get("MIN_LEADS") or 5)
FATIGUE_FREQ = float(os.environ.get("FATIGUE_FREQ") or 2.5)


def _is_reg(a):
    a = (a or "").lower()
    return "complete_registration" in a or a == "lead" or a.endswith(".lead") or "registration" in a


def _leads(actions):
    n = 0
    for a in (actions or []):
        if _is_reg(a.get("action_type")):
            n += int(float(a.get("value", 0) or 0))
    return n


def pull(account, preset, extra_fields=()):
    out = []
    params = {"level": "ad", "date_preset": preset, "limit": 1000,
              "fields": ["ad_name", "spend", "impressions", "actions", *extra_fields]}
    for r in C.fb_retry(account.get_insights, params=params):
        out.append(r)
    return out


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)

    # A: 歷史
    hist = defaultdict(lambda: {"spend": 0.0, "leads": 0, "impr": 0})
    for r in pull(account, "maximum"):
        nm = (r.get("ad_name") or "").strip()
        if not nm:
            continue
        h = hist[nm]
        h["spend"] += float(r.get("spend", 0) or 0)
        h["leads"] += _leads(r.get("actions"))
        h["impr"] += int(float(r.get("impressions", 0) or 0))

    # B: 近14天 frequency(抓疲勞)
    freq14 = {}
    try:
        for r in pull(account, "last_14d", extra_fields=["frequency", "reach"]):
            nm = (r.get("ad_name") or "").strip()
            if not nm:
                continue
            f = float(r.get("frequency", 0) or 0)
            sp = float(r.get("spend", 0) or 0)
            cur = freq14.get(nm)
            if not cur or sp > cur["spend"]:
                freq14[nm] = {"freq": f, "spend": sp}
    except Exception as e:
        print(f"(近14天 frequency 讀取略過: {str(e)[:80]})")

    rows = []
    for nm, h in hist.items():
        cpl = (h["spend"] / h["leads"]) if h["leads"] else None
        rows.append({"name": nm, **h, "cpl": cpl})

    tot = sum(r["spend"] for r in rows)
    print("SCAN_START")
    print(f"全帳號歷史：{len(rows)} 支廣告有紀錄 · 總花費={tot:,.0f} TWD")
    print(f"門檻：潛力股=歷史花費 {MIN_SPENT:.0f}~{POT_MAX:.0f}、報名≥{MIN_LEADS}、CPL≤{GOOD_CPL:.0f}"
          f" · 幾乎沒投<{MIN_SPENT:.0f} · 疲勞=近14天 freq≥{FATIGUE_FREQ}")

    # 1) 低花費潛力股
    pot = [r for r in rows if MIN_SPENT <= r["spend"] <= POT_MAX
           and r["leads"] >= MIN_LEADS and r["cpl"] is not None and r["cpl"] <= GOOD_CPL]
    pot.sort(key=lambda x: x["cpl"])
    print(f"\n== 🟢 低花費潛力股（花得少、CPL 不錯 → 值得加碼/重跑）{len(pot)} 支 ==")
    print(f"{'廣告':46s} {'歷史花費':>8s} {'報名':>5s} {'CPL':>6s}")
    for r in pot[:30]:
        print(f"{r['name'][:44]:46s} {r['spend']:8,.0f} {r['leads']:5d} {r['cpl']:6,.0f}")

    # 2) 幾乎沒投過（有曝光但花費極低）
    never = [r for r in rows if r["spend"] < MIN_SPENT and r["impr"] > 0]
    never.sort(key=lambda x: -x["spend"])
    print(f"\n== ⚪ 幾乎沒投過（歷史花費<{MIN_SPENT:.0f}，根本沒被好好測）{len(never)} 支 ==")
    for r in never[:30]:
        c = f"{r['cpl']:,.0f}" if r["cpl"] else "—"
        print(f"{r['name'][:44]:46s} {r['spend']:8,.0f} 報名{r['leads']:>3d} CPL {c}")

    # 3) 近14天疲勞
    fat = [(nm, d) for nm, d in freq14.items() if d["freq"] >= FATIGUE_FREQ and d["spend"] > 0]
    fat.sort(key=lambda x: -x[1]["freq"])
    print(f"\n== 🔴 近14天疲勞（frequency≥{FATIGUE_FREQ}，該換素材）{len(fat)} 支 ==")
    for nm, d in fat[:20]:
        print(f"{nm[:44]:46s} freq {d['freq']:.2f} · 近14天花費 {d['spend']:,.0f}")
    print("\nSCAN_END")


if __name__ == "__main__":
    run()
