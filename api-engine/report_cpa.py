"""
一次性：列出每個 campaign 的『歷史總花費』(maximum 期間) + 報名數。
用來跟 paid list 的買單數對算真 CPA。輸出純文字，方便貼回分析。

用法: python report_cpa.py
"""
import config as C
from facebook_business.adobjects.adaccount import AdAccount


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    print("CAMPAIGN_SPEND_REPORT_START")
    for camp in account.get_campaigns(fields=["id", "name", "effective_status"],
                                       params={"limit": 300}):
        spend = 0.0
        results = 0
        try:
            ins = camp.get_insights(params={"date_preset": "maximum"},
                                    fields=["spend", "actions"])
            if ins:
                row = ins[0]
                spend = float(row.get("spend", 0) or 0)
                for a in (row.get("actions") or []):
                    if ("registration" in a["action_type"] or "lead" in a["action_type"]
                            or "purchase" in a["action_type"]):
                        results += int(float(a["value"]))
        except Exception as e:
            print(f"ROW\t{camp.get('name','')}\tERR\t{e}")
            continue
        # 用 tab 分隔，好解析
        print(f"ROW\t{camp.get('name','')}\t{spend:.0f}\t{results}\t{camp.get('effective_status','')}")
    print("CAMPAIGN_SPEND_REPORT_END")


if __name__ == "__main__":
    run()
