"""
自动上广告 (Path B / Marketing API 直连) — 复制 Soo Cheng 结构到 AI 回覆 幫你獲客 帳號。

对每个 angle 建：Campaign(CBO) → Ad Set(pixel转换) → N 支 Creative → N 支 Ad，全部 PAUSED。
读 config/launch_template.yaml + config/angles.yaml，跟 MCP 版共用同一份设定。

用法:
  python launch.py --round R1 --angles BROAD,BUSINESS_OWNER
  python launch.py --round R1              # 只跑 priority=1 的角度
"""
import argparse
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.advideo import AdVideo


def upload_video(account, path):
    """上传影片，回传 video_id。CI 環境沒有本機檔，優先用 URL。
    path 是 http(s) 連結 → Meta 直接抓；否則當本機路徑上傳。"""
    if str(path).startswith("http"):
        video = account.create_ad_video(params={"file_url": path})
    else:
        video = account.create_ad_video(params={"source": path})
    return video["id"]


def _custom_event_type():
    """依 CONVERSION_EVENT / OBJECTIVE 決定 pixel 事件枚舉。"""
    ev = (C.CONVERSION_EVENT or "").lower()
    if "lead" in ev or C.OBJECTIVE == "OUTCOME_LEADS":
        return "LEAD"
    if "purchase" in ev:
        return "PURCHASE"
    return "COMPLETE_REGISTRATION"


def create_campaign(account, name):
    params = {
        "name": name,
        "objective": C.OBJECTIVE,
        "special_ad_categories": [],
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",   # = Highest volume
        "daily_budget": C.to_minor(C.load_yaml("launch_template.yaml")["ad_set"]["daily_budget_myr"]),
        "status": "PAUSED",
    }
    return account.create_campaign(params=params)["id"]


def create_ad_set(account, campaign_id, name, angle):
    tmpl = C.load_yaml("launch_template.yaml")["ad_set"]
    targeting = {
        "geo_locations": {"countries": tmpl["geo"]["countries"]},
        "age_min": tmpl["age_min"],
        "age_max": tmpl["age_max"],
    }
    if angle.get("detailed_targeting"):
        # 兴趣定向：正式跑前建议用 targetingsearch 换成真实 interest id
        targeting["flexible_spec"] = [
            {"interests": [{"name": kw} for kw in angle["detailed_targeting"]]}
        ]
    params = {
        "name": name,
        "campaign_id": campaign_id,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "promoted_object": {
            "pixel_id": C.PIXEL_ID,
            "custom_event_type": _custom_event_type(),
        },
        "targeting": targeting,
        "status": "PAUSED",
        # CBO 在 campaign 层下预算，adset 不再设 daily_budget
    }
    return account.create_ad_set(params=params)["id"]


def create_creative(account, video_id, cr):
    tmpl = C.load_yaml("launch_template.yaml")["creative_defaults"]
    story = {
        "page_id": C.PAGE_ID,
        "video_data": {
            "video_id": video_id,
            "message": cr["primary_text"],
            "title": cr["headline"],
            "call_to_action": {
                "type": tmpl["call_to_action"],
                "value": {"link": C.LANDING_URL},
            },
        },
    }
    if C.INSTAGRAM_ID:
        story["instagram_actor_id"] = C.INSTAGRAM_ID
    params = {"name": cr["video"], "object_story_spec": story}
    return account.create_ad_creative(params=params)["id"]


def create_ad(account, adset_id, creative_id, name):
    params = {
        "name": name,
        "adset_id": adset_id,
        "creative": {"creative_id": creative_id},
        "status": "PAUSED",
    }
    return account.create_ad(params=params)["id"]


def run(round_tag, only_angles=None):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    tmpl = C.load_yaml("launch_template.yaml")
    brand = tmpl["brand"]["code"]
    creatives = tmpl["creatives"]
    angles = C.load_yaml("angles.yaml")["angles"]

    if only_angles:
        angles = [a for a in angles if a["key"].replace(" ", "_") in only_angles]
    else:
        angles = [a for a in angles if a.get("priority", 2) == 1]

    print(f"[launch] 帳號 {C.AD_ACCOUNT_ID} | {len(angles)} 角度 | 每组 {len(creatives)} 支素材 | DRY_RUN={C.DRY_RUN}")

    # 上架前檢查必填，缺了就明確報錯(避免建到一半失敗)
    if not C.DRY_RUN:
        missing = [k for k, v in {"PAGE_ID": C.PAGE_ID, "PIXEL_ID": C.PIXEL_ID,
                                  "LANDING_URL": C.LANDING_URL}.items() if not v]
        if missing:
            raise SystemExit(f"缺少必填: {', '.join(missing)}。先跑 discover.py 取得 ID，"
                             f"填進 Secrets 再上架。")

    for angle in angles:
        base = f"{brand} | {angle['key']} | {round_tag}"
        if C.DRY_RUN:
            print(f"  [dry] 会建 campaign: {base} + {len(creatives)} 支广告 (全 PAUSED)")
            continue

        camp_id = create_campaign(account, base)
        adset_id = create_ad_set(account, camp_id, base, angle)
        for i, cr in enumerate(creatives, 1):
            vid = cr.get("video_id") or upload_video(account, cr.get("video_url") or cr["video"])
            creative_id = create_creative(account, vid, cr)
            ad_id = create_ad(account, adset_id, creative_id, f"{base}-{i}")
            print(f"  ✓ {base}-{i}  ad={ad_id}")
        print(f"  → campaign {camp_id} 建好 (PAUSED)。检查无误后用 Ads Manager 或 optimize 开 ACTIVE。")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--round", default="R1", help="本轮标记，如 R1")
    p.add_argument("--angles", default="", help="逗号分隔角度 key(空则跑 priority=1)")
    args = p.parse_args()
    only = [a.strip() for a in args.angles.split(",") if a.strip()] or None
    run(args.round, only)
