"""
精準重開指定的 ad set(只動這幾個,不碰其他)。
- TARGET_ADSETS：要開的 ad set id(逗號分隔)。
- 對每個:印出 母campaign(名稱/狀態/是否CBO)、ad set(名稱/狀態/日預算)、裡面每支廣告(名稱/狀態)。
- 計畫:設 ad set ACTIVE;母 campaign 若沒開就一起開(標註 CBO 風險);若整組廣告都關,提示要開一支。
- DRY_RUN=true(預設)只印計畫不動手;=false 才真的執行。
只印彙總,無個資。
"""
import os
import config as C
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.ad import Ad

DRY = (os.environ.get("DRY_RUN", "true").lower() != "false")
DEFAULT_TARGETS = [
    "120242383001900658",  # *|30-60|Manual        20單 ROAS3.07 ⭐
    "120243049707190658",  # Advertising/Agri       5單 ROAS2.92
    "120243049707180658",  # Cosmetics|30-55        4單 ROAS3.26
    "120242427823100658",  # Health&wellness        2單 ROAS8.80
    "120242488967560658",  # LINE/media             2單 ROAS6.71
    "120244979397590658",  # *|25-65+|*             2單 ROAS2.82
]
TARGETS = [x.strip() for x in (os.environ.get("TARGET_ADSETS") or ",".join(DEFAULT_TARGETS)).split(",") if x.strip()]


def run():
    C.init_api()
    print(f"ACTIVATE_PLAN_START · DRY_RUN={DRY} · {len(TARGETS)} 個 ad set")
    for aid in TARGETS:
        try:
            a = C.fb_retry(AdSet(aid).api_get,
                           fields=["name", "effective_status", "status", "daily_budget", "campaign_id"])
        except Exception as e:
            print(f"\n[{aid}] ⚠️ 讀取失敗: {e}")
            continue
        cid = a.get("campaign_id")
        camp = C.fb_retry(Campaign(cid).api_get,
                          fields=["name", "effective_status", "daily_budget"]) if cid else {}
        cbo = float(camp.get("daily_budget", 0) or 0) > 0
        ads = C.fb_retry(AdSet(aid).get_ads, fields=["name", "effective_status"], params={"limit": 50})
        ad_list = [(ad.get("name", ""), ad.get("effective_status", "")) for ad in ads]
        any_active_ad = any(s == "ACTIVE" for _, s in ad_list)

        print(f"\n── ad set {aid}")
        print(f"   Campaign：{camp.get('name','?')}  [{camp.get('effective_status','?')}]"
              f"{' · CBO(預算在campaign)' if cbo else ' · ABO(預算在adset)'}")
        print(f"   Ad set  ：{a.get('name','?')}  [{a.get('effective_status','?')}] · 日預算 "
              f"{float(a.get('daily_budget',0) or 0)/C.currency_offset():,.0f}")
        for nm, st in ad_list:
            print(f"      廣告：{nm[:46]:46s} [{st}]")
        # 計畫
        plan = []
        if camp and camp.get("effective_status") != "ACTIVE":
            plan.append("開母 campaign" + ("（CBO：只留此 ad set 開、其餘保持關）" if cbo else ""))
        if a.get("effective_status") != "ACTIVE":
            plan.append("開此 ad set")
        if not any_active_ad:
            plan.append("⚠️ 整組廣告都關 → 需開至少一支(預設開第一支)")
        print(f"   計畫：{'；'.join(plan) if plan else '已在跑,無需動作'}")

        if not DRY:
            if camp and camp.get("effective_status") != "ACTIVE":
                C.fb_retry(Campaign(cid).api_update, params={"status": "ACTIVE"})
            if a.get("effective_status") != "ACTIVE":
                C.fb_retry(AdSet(aid).api_update, params={"status": "ACTIVE"})
            if not any_active_ad and ad_list:
                first_id = ads[0]["id"] if ads else None
                if first_id:
                    C.fb_retry(Ad(first_id).api_update, params={"status": "ACTIVE"})
            print("   ✅ 已執行")
    print("ACTIVATE_PLAN_END" + ("（dry：未動）" if DRY else " ⚡已真的開"))


if __name__ == "__main__":
    run()
