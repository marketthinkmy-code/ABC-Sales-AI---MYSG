"""
自动跑 / 每日优化 (Path B) — 复制 Soo Cheng 的 kill/scale/duplicate 逻辑。

拉近 3 天 campaign insights → 套 config/.env 门槛 → PAUSE / 加预算 / 复制赢家。
DRY_RUN=true 时只印建议不动手。挂 cron / GitHub Actions 每天跑一次。

用法:
  python optimize.py
"""
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign


def fetch_campaigns(account):
    fields = ["id", "name", "status", "daily_budget", "effective_status"]
    camps = account.get_campaigns(fields=fields, params={"limit": 200})
    rows = []
    for c in camps:
        if c.get("effective_status") not in ("ACTIVE",):
            continue
        insights = c.get_insights(params={"date_preset": "last_3d"}, fields=[
            "spend", "actions", "cost_per_action_type", "impressions", "ctr",
        ])
        spend, results, cpl = 0.0, 0, None
        if insights:
            row = insights[0]
            spend = float(row.get("spend", 0) or 0)
            for a in (row.get("actions") or []):
                if a["action_type"] in ("offsite_conversion.fb_pixel_complete_registration",
                                        "complete_registration", "lead", "onsite_conversion.lead_grouped"):
                    results += int(float(a["value"]))
            for cpa in (row.get("cost_per_action_type") or []):
                if "registration" in cpa["action_type"] or "lead" in cpa["action_type"]:
                    cpl = float(cpa["value"])
        if cpl is None and results:
            cpl = spend / results
        rows.append({
            "obj": c, "id": c["id"], "name": c["name"],
            "daily_budget": float(c.get("daily_budget", 0) or 0) / 100.0,
            "spend": spend, "results": results, "cpl": cpl,
        })
    return rows


def decide(r):
    """回传 (action, reason)。门槛全来自 .env。"""
    if r["spend"] < C.MIN_SPEND_BEFORE_ACTION:
        return ("SKIP", f"观察期 (花 {r['spend']:.0f} < {C.MIN_SPEND_BEFORE_ACTION:.0f})")
    if r["results"] == 0 and r["spend"] >= 2 * C.TARGET_CPL:
        return ("PAUSE", f"零成果烧 {r['spend']:.0f}")
    if r["cpl"] and r["cpl"] > C.KILL_CPL:
        return ("PAUSE", f"CPL {r['cpl']:.0f} > {C.KILL_CPL:.0f}")
    if r["cpl"] and r["cpl"] < 0.7 * C.TARGET_CPL and r["results"] >= 5:
        return ("DUPLICATE", f"极佳 CPL {r['cpl']:.0f}, 复制放大")
    if r["cpl"] and r["cpl"] < C.SCALE_CPL and r["spend"] >= 3 * C.TARGET_CPL:
        return ("SCALE", f"CPL {r['cpl']:.0f} < {C.SCALE_CPL:.0f}, 加预算")
    return ("KEEP", f"CPL {r['cpl'] and round(r['cpl'])}")


def apply(r, action):
    camp = Campaign(r["id"])
    if action == "PAUSE":
        camp.api_update(params={"status": "PAUSED"})
    elif action == "SCALE":
        new_budget = min(r["daily_budget"] * (1 + C.BUDGET_STEP_PCT / 100), C.MAX_DAILY_BUDGET)
        camp.api_update(params={"daily_budget": C.to_minor(new_budget)})
    elif action == "DUPLICATE":
        camp.create_copy(params={"deep_copy": True, "status_option": "PAUSED"})


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    rows = fetch_campaigns(account)
    print(f"[optimize] {C.AD_ACCOUNT_ID} | {len(rows)} 支 ACTIVE | "
          f"目標CPA<{C.TARGET_CPL:.0f} 關>{C.KILL_CPL:.0f} | DRY_RUN={C.DRY_RUN}")

    # --- CPA 報表：花費 / 報名數 / CPA 一覽 ---
    print("  " + "-" * 78)
    print(f"  {'廣告 (Campaign)':32} | {'花費':>8} | {'報名':>5} | {'CPA':>7} | 動作")
    print("  " + "-" * 78)

    pauses = [r for r in rows if decide(r)[0] == "PAUSE"]
    if len(pauses) > 10:
        print(f"⚠️ 保护栏: 要关 {len(pauses)} 支 (>10)，停手不执行，请人工检查。")
        return

    total_spend = total_results = 0.0
    for r in rows:
        action, reason = decide(r)
        cpa = f"{r['cpl']:.0f}" if r['cpl'] else "-"
        total_spend += r["spend"]
        total_results += r["results"]
        print(f"  {r['name'][:32]:32} | {r['spend']:>8.0f} | {r['results']:>5} | "
              f"{cpa:>7} | {action} ({reason})")
        if not C.DRY_RUN and action in ("PAUSE", "SCALE", "DUPLICATE"):
            apply(r, action)

    avg = total_spend / total_results if total_results else 0
    print("  " + "-" * 78)
    print(f"  合計: 花費 {total_spend:.0f} | 報名 {total_results:.0f} | 平均CPA {avg:.0f} TWD")
    print("完成。" + ("(dry run，未真的改)" if C.DRY_RUN else " ⚡真跑，已執行動作"))


if __name__ == "__main__":
    run()
