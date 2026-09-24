"""
預約型 campaign 重構放大 —— 解掉「花不動」再把『剩餘預算 ÷ 剩餘天數』鋪下去。

三步(DRY_RUN=true 只印計畫,不動):
  1. 關掉 loser ad set(視窗 CPL > LOSER_CPL 的)。
  2. 放寬存活 ad set 的投放天花板:Advantage 受眾 ON + 自動(Advantage+)版位,
     年齡維持 30-55(靠 advantage_audience 自動外擴,不亂改 ICP)。
  3. 配速:每日總預算 =(目標總額 − 已花)÷ 剩餘天數,平均分到存活 ad set。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID,
     CAMP_ID(預設預約型), SINCE(CPL 視窗起, 預設 2026-08-25),
     TARGET_TOTAL_TWD(預設 72500 = RM10k@7.25), END_DATE(YYYY-MM-DD, 預設下一個週三),
     LOSER_CPL(預設 160), MIN_ADSET(預設 300), MAX_ADSET(預設 20000),
     DRY_RUN(預設 true)
"""
import os, datetime as dt
import config as C
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from spend_audit import _is_reg

CAMP_ID = os.environ.get("CAMP_ID") or "120246810049310658"
SINCE = os.environ.get("SINCE") or "2026-08-25"
TARGET_TOTAL = float(os.environ.get("TARGET_TOTAL_TWD") or 72500)
LOSER_CPL = float(os.environ.get("LOSER_CPL") or 160)
MIN_ADSET = float(os.environ.get("MIN_ADSET") or 300)
MAX_ADSET = float(os.environ.get("MAX_ADSET") or 20000)
OFF = C.currency_offset()   # TWD=1
DRY = (os.environ["DRY_RUN"].lower() != "false") if os.environ.get("DRY_RUN") else True


def end_date():
    s = os.environ.get("END_DATE")
    if s:
        return dt.date.fromisoformat(s)
    today = dt.date.today()
    return today + dt.timedelta(days=(2 - today.weekday()) % 7)   # 下一個週三(含今天)


def adset_window(aset_id):
    tr = {"since": SINCE, "until": dt.date.today().isoformat()}
    spend, reg = 0.0, 0
    try:
        ins = C.fb_retry(AdSet(aset_id).get_insights, params={"time_range": tr},
                         fields=["spend", "actions"])
        if ins:
            spend = float(ins[0].get("spend", 0) or 0)
            for a in (ins[0].get("actions") or []):
                if _is_reg(a["action_type"]):
                    reg += int(float(a["value"]))
    except Exception as e:
        print(f"    ⚠️ insights 失敗 {aset_id}: {str(e)[:70]}")
    return spend, reg


def broadened_targeting():
    # 沿用建立時「已被接受」的定向(台灣·30-55·繁中22·手動版位),只把 Advantage 受眾打開。
    # 不動版位(改自動版位會被 Meta 擋),降低被拒風險。
    return {
        "geo_locations": {"countries": ["TW"]},
        "age_min": 30, "age_max": 55,
        "locales": [22],
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "facebook_reels", "story"],
        "instagram_positions": ["stream", "reels", "story"],
        "targeting_automation": {"advantage_audience": 1},
    }


def _err(e):
    parts = []
    for m in ("api_error_code", "api_error_subcode", "api_error_message"):
        try:
            v = getattr(e, m)()
            if v:
                parts.append(f"{m}={v}")
        except Exception:
            pass
    return " · ".join(parts) or str(e).replace("\n", " ")[:200]


def lifetime_spend():
    try:
        ins = C.fb_retry(Campaign(CAMP_ID).get_insights,
                         params={"date_preset": "maximum"}, fields=["spend"])
        if ins:
            return float(ins[0].get("spend", 0) or 0)
    except Exception as e:
        print(f"  ⚠️ 讀 campaign 總花費失敗: {e}")
    return 0.0


def run():
    C.init_api()
    end = end_date()
    today = dt.date.today()
    rem_days = max(1, (end - today).days + 1)
    camp = C.fb_retry(Campaign(CAMP_ID).api_get, fields=["name", "effective_status"])
    spent = lifetime_spend()
    remaining = max(0.0, TARGET_TOTAL - spent)
    daily_total = remaining / rem_days

    print(f"[restructure+scale] {camp.get('name','')}  狀態={camp.get('effective_status')}  DRY_RUN={DRY}")
    print(f"  目標總額 {TARGET_TOTAL:.0f} − 已花 {spent:.0f} = 剩餘 {remaining:.0f} TWD")
    print(f"  結束日 {end}(剩 {rem_days} 天,含今天)→ 每日總預算 {daily_total:.0f} TWD")

    asets = list(C.fb_retry(Campaign(CAMP_ID).get_ad_sets,
                            fields=["name", "effective_status", "daily_budget"],
                            params={"limit": 100}))
    losers, survivors = [], []
    for i, a in enumerate(asets, 1):
        sp, reg = adset_window(a["id"])
        cpl = sp / reg if reg else None
        rec = {"idx": i, "id": a["id"], "name": a.get("name", ""),
               "status": a.get("effective_status", ""), "cpl": cpl, "reg": reg, "spend": sp}
        # loser:CPL 過高,或有花費卻幾乎沒報名
        if (cpl is not None and cpl > LOSER_CPL) or (sp >= 800 and reg < 6):
            losers.append(rec)
        else:
            survivors.append(rec)

    # 只把「還會花錢」的存活組拿來分預算(本來就 ACTIVE 的);PAUSED 的存活組先不管
    active_survivors = [s for s in survivors if s["status"] == "ACTIVE"]
    n = len(active_survivors) or 1
    per = max(MIN_ADSET, min(MAX_ADSET, daily_total / n))

    def cplstr(r):
        return f"{r['cpl']:.0f}" if r["cpl"] else "—"

    print("  " + "-" * 92)
    print(f"  關閉 loser(CPL>{LOSER_CPL:.0f}):{len(losers)} 組")
    for r in sorted(losers, key=lambda x: -(x["cpl"] or 0)):
        print(f"     ✗ 組{r['idx']:<2} {r['status']:<8} CPL {cplstr(r):>5} · 報名 {r['reg']} → PAUSE")
    total_new = per * len(active_survivors)
    print(f"  放寬+配速 存活 ACTIVE:{len(active_survivors)} 組 · 每組日預算 {per:.0f} TWD"
          f"(合計 {total_new:.0f}/日)")
    for r in sorted(active_survivors, key=lambda x: (x["cpl"] or 9e9)):
        print(f"     ✓ 組{r['idx']:<2} CPL {cplstr(r):>5} · 報名 {r['reg']:>3} "
              f"→ Advantage受眾ON+自動版位 · 日預算→{per:.0f}")
    other = [s for s in survivors if s["status"] != "ACTIVE"]
    if other:
        tags = ", ".join(f"組{r['idx']}" for r in other)
        print(f"  (存活但非 ACTIVE,先不動:{tags})")
    print("  " + "-" * 92)

    if DRY:
        print("  （DRY:未動任何東西。確認數字後再 live=true 執行。）")
        return

    # --- 執行 ---
    for r in losers:
        if r["status"] != "PAUSED":
            try:
                C.fb_retry(AdSet(r["id"]).api_update, params={"status": "PAUSED"})
                print(f"  ✓ 關 組{r['idx']}")
            except Exception as e:
                print(f"  ⚠️ 關 組{r['idx']} 失敗: {str(e)[:70]}")
    tgt = broadened_targeting()
    for r in active_survivors:
        # 1) 配速:設日預算(這是「放大」的本體,先確保它成功)
        try:
            C.fb_retry(AdSet(r["id"]).api_update, params={"daily_budget": C.to_minor(per)})
            print(f"  ✓ 配速 組{r['idx']} 日預算→{per:.0f}")
        except Exception as e:
            print(f"  ⚠️ 組{r['idx']} 預算失敗: {_err(e)}")
        # 2) 放寬:打開 Advantage 受眾(best-effort,失敗不影響預算)
        try:
            C.fb_retry(AdSet(r["id"]).api_update, params={"targeting": tgt})
            print(f"  ✓ 放寬 組{r['idx']} Advantage受眾ON")
        except Exception as e:
            print(f"  ⚠️ 組{r['idx']} 放寬失敗: {_err(e)}")
    print(f"→ 完成。存活 {len(active_survivors)} 組 × {per:.0f}/日 ≈ {per*len(active_survivors):.0f} TWD/日,"
          f"配速到 {end}。")
    print("  ⓘ 放寬會讓 ad set 重新進 learning(1-2 天 CPL 可能先波動再穩)。")


if __name__ == "__main__":
    run()
