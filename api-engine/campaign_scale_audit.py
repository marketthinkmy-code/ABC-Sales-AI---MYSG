"""
單一 campaign 的『每個 ad set』體檢 —— 專門診斷「花不動(underspend) + CPL 高」。

對每個 ad set 拉:狀態 · 日預算 · 花費 · 日均花費 · 花費達成率(日均/日預算) ·
曝光 · 觸及 · 頻率 · 報名數 · CPL · CTR。再算 campaign 合計與診斷提示。

只讀不改(除非之後另開 scale 腳本)。不印任何個資。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, CAMP_ID(選填,預設預約型那條),
     SINCE(選填 YYYY-MM-DD,預設 2026-08-25), UNTIL(選填,預設今天)
"""
import os, datetime as dt
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from spend_audit import _is_reg

CAMP_ID = os.environ.get("CAMP_ID") or "120246810049310658"
SINCE = os.environ.get("SINCE") or "2026-08-25"
UNTIL = os.environ.get("UNTIL") or dt.date.today().isoformat()
OFF = C.currency_offset()   # TWD=1


def _days(since, until):
    a = dt.date.fromisoformat(since)
    b = dt.date.fromisoformat(until)
    return max(1, (b - a).days + 1)


def adset_insight(aset_id):
    tr = {"since": SINCE, "until": UNTIL}
    spend = imp = reach = 0.0
    reg = 0
    freq = ctr = 0.0
    try:
        ins = C.fb_retry(AdSet(aset_id).get_insights,
                         params={"time_range": tr},
                         fields=["spend", "impressions", "reach", "frequency", "ctr", "actions"])
    except Exception as e:
        print(f"    ⚠️ insights 失敗 {aset_id}: {str(e)[:80]}")
        ins = []
    if ins:
        r = ins[0]
        spend = float(r.get("spend", 0) or 0)
        imp = float(r.get("impressions", 0) or 0)
        reach = float(r.get("reach", 0) or 0)
        freq = float(r.get("frequency", 0) or 0)
        ctr = float(r.get("ctr", 0) or 0)
        for a in (r.get("actions") or []):
            if _is_reg(a["action_type"]):
                reg += int(float(a["value"]))
    return {"spend": spend, "imp": imp, "reach": reach, "freq": freq, "ctr": ctr, "reg": reg}


def run():
    C.init_api()
    camp = C.fb_retry(Campaign(CAMP_ID).api_get,
                      fields=["name", "effective_status", "daily_budget", "lifetime_budget",
                              "bid_strategy"])
    cname = camp.get("name", "")
    days = _days(SINCE, UNTIL)
    print(f"[campaign 體檢] {cname}")
    print(f"  id={CAMP_ID} · 狀態={camp.get('effective_status')} · "
          f"bid={camp.get('bid_strategy')} · 視窗 {SINCE}~{UNTIL}({days} 天)")

    asets = list(C.fb_retry(Campaign(CAMP_ID).get_ad_sets,
                            fields=["name", "effective_status", "daily_budget"],
                            params={"limit": 100}))
    print(f"  ad set 數:{len(asets)}")
    print("  " + "-" * 110)
    print(f"  {'#':>2} {'狀態':<14} {'日預算':>7} {'花費':>8} {'日均':>7} {'達成%':>6} "
          f"{'報名':>4} {'CPL':>7} {'觸及':>7} {'頻率':>5} {'CTR%':>5}")
    print("  " + "-" * 110)

    tot_budget = tot_spend = tot_reg = 0.0
    active_budget = 0.0
    n_active = 0
    rows = []
    for i, a in enumerate(asets, 1):
        st = a.get("effective_status", "")
        db = float(a.get("daily_budget", 0) or 0) / OFF
        ins = adset_insight(a["id"])
        sp, reg = ins["spend"], ins["reg"]
        daily = sp / days
        ratio = (daily / db * 100) if db else 0
        cpl = sp / reg if reg else None
        tot_budget += db
        tot_spend += sp
        tot_reg += reg
        if st == "ACTIVE":
            active_budget += db
            n_active += 1
        rows.append((i, st, db, sp, daily, ratio, reg, cpl, ins))
        print(f"  {i:>2} {st:<14} {db:>7.0f} {sp:>8.0f} {daily:>7.0f} {ratio:>5.0f}% "
              f"{reg:>4} {(f'{cpl:.0f}' if cpl else '—'):>7} "
              f"{ins['reach']:>7.0f} {ins['freq']:>5.2f} {ins['ctr']:>5.2f}")

    print("  " + "-" * 110)
    blended_cpl = tot_spend / tot_reg if tot_reg else None
    daily_spend = tot_spend / days
    print(f"  合計:日預算 {tot_budget:.0f} TWD(ACTIVE {n_active} 組={active_budget:.0f}) · "
          f"花費 {tot_spend:.0f} · 日均花費 {daily_spend:.0f} · "
          f"報名 {tot_reg:.0f} · 綜合CPL {(f'{blended_cpl:.0f}' if blended_cpl else '—')} TWD")
    if active_budget:
        print(f"  花費達成率(日均/ACTIVE日預算):{daily_spend/active_budget*100:.0f}%"
              f"  ← 低於 ~70% 就是『花不動』")
    print()
    print("  診斷提示:")
    print("   · 花不動(達成%低):版位窄/受眾窄/新 pixel 訊號不足→演算法保守;加預算解決不了。")
    print("   · CPL 高但花得動:受眾/素材問題,或優化事件太少觸發。")
    print("   · 多組窄受眾互搶(auction overlap):17 組同池會彼此競價,建議整併。")


if __name__ == "__main__":
    run()
