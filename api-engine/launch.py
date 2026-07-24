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


def delete_existing_campaigns(account, name):
    """刪掉同名的 PAUSED campaign(上次失敗留下的空殼)，讓 launch 可重跑不留垃圾。"""
    try:
        for c in account.get_campaigns(fields=["id", "name", "effective_status"],
                                       params={"limit": 200}):
            if c.get("name") == name and c.get("effective_status") in ("PAUSED", "CAMPAIGN_PAUSED"):
                Campaign(c["id"]).api_delete()
                print(f"  (清掉同名空 campaign {c['id']})")
    except Exception as e:
        print(f"  (清理同名 campaign 略過: {e})")


def source_objective():
    """讀複製來源 ad set 的母 campaign objective，讓新 campaign 對齊(否則複製會 Objective Mismatch)。
    重試數次；讀不到就丟錯，絕不亂猜(猜錯 objective 會導致複製失敗)。"""
    last = None
    for _ in range(4):
        try:
            camp_id = AdSet(C.CLONE_SOURCE_ADSET).api_get(fields=["campaign_id"])["campaign_id"]
            return Campaign(camp_id).api_get(fields=["objective"])["objective"]
        except Exception as e:
            last = e
    raise RuntimeError(f"無法讀取來源 ad set {C.CLONE_SOURCE_ADSET} 的 objective: {last}")


def create_campaign(account, name, with_budget=True, objective=None):
    params = {
        "name": name,
        "objective": objective or C.OBJECTIVE,
        "special_ad_categories": [],
        "status": "PAUSED",
    }
    if with_budget:
        # CBO：預算+出價策略在 campaign 層
        params["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"   # = Highest volume
        params["daily_budget"] = C.to_minor(
            C.load_yaml("launch_template.yaml")["ad_set"]["daily_budget_myr"])
    else:
        # ABO：預算+出價策略在 ad set 層；campaign 不設 bid_strategy(否則 Meta 要求 campaign budget)
        params["is_adset_budget_sharing_enabled"] = False
    return account.create_campaign(params=params)["id"]


def clone_compliant_adset(account, campaign_id, name):
    """複製一個現有已合規的 ad set(繼承台灣廣告主聲明)，清掉舊廣告，回傳新 ad set id。
    這是繞過 Taiwan 'No advertiser information' 的可靠做法。"""
    budget = C.load_yaml("launch_template.yaml")["ad_set"]["daily_budget_myr"]
    resp = AdSet(C.CLONE_SOURCE_ADSET).create_copy(params={
        "campaign_id": campaign_id,
        "status_option": "PAUSED",
    })
    # 取新 ad set id(SDK 回傳形狀可能不同，逐一嘗試)
    new_id = (resp.get("copied_adset_id") or resp.get("id")
              or (resp.get("ad_object_ids") or {}).get("adset")) if hasattr(resp, "get") else None
    if not new_id:
        new_id = resp["copied_adset_id"]
    new_aset = AdSet(new_id)
    new_aset.api_update(params={"name": name, "daily_budget": C.to_minor(budget),
                                "status": "PAUSED"})
    # 刪掉複製過來的舊廣告，改放我們的贏家
    for ad in new_aset.get_ads(fields=["id"]):
        try:
            Ad(ad["id"]).api_delete()
        except Exception:
            pass
    return new_id


def copy_winner_ads(account, adset_id, keywords, base):
    """依名稱關鍵字找現有贏家廣告，複製進新 ad set，沿用舊 creative → 繞過 dev-mode。"""
    # 掃帳號現有廣告的 id+name，逐關鍵字找第一個含該 hook 的廣告
    all_ads = []
    for ad in account.get_ads(fields=["id", "name"], params={"limit": 1000}):
        all_ads.append({"id": ad["id"], "name": ad.get("name", "")})
    print(f"  掃到 {len(all_ads)} 支現有廣告，開始比對關鍵字")
    count = 0
    for i, kw in enumerate(keywords, 1):
        match = next((a for a in all_ads if kw in a["name"]), None)
        if not match:
            print(f"  ⚠️ 找不到名稱含「{kw}」的現有廣告，跳過")
            continue
        resp = Ad(match["id"]).create_copy(params={"adset_id": adset_id,
                                                   "status_option": "PAUSED"})
        new_ad = (resp.get("copied_ad_id") or resp.get("id")) if hasattr(resp, "get") else None
        try:
            if new_ad:
                Ad(new_ad).api_update(params={"name": f"{base} | {kw}"})
        except Exception:
            pass
        count += 1
        print(f"  ✓ 複製贏家「{kw}」(來源 ad {match['id']}) → ad {new_ad}")
    return count


def create_ad_set(account, campaign_id, name, angle):
    tmpl = C.load_yaml("launch_template.yaml")["ad_set"]
    countries = tmpl["geo"]["countries"]
    targeting = {
        "geo_locations": {"countries": countries},
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
    # 台灣法規：投放含台灣地區必須聲明 regional regulated category + 廣告主/付款方。
    if "TW" in countries:
        params["regional_regulated_categories"] = ["TAIWAN_UNIVERSAL"]
        if C.DSA_BENEFICIARY:
            params["dsa_beneficiary"] = C.DSA_BENEFICIARY
        if C.DSA_PAYOR:
            params["dsa_payor"] = C.DSA_PAYOR
    return account.create_ad_set(params=params)["id"]


def video_thumbnail(video_id):
    """取影片縮圖 uri(Meta 建影片 creative 時必填 image_url)。"""
    try:
        thumbs = list(AdVideo(video_id).get_thumbnails(fields=["uri", "is_preferred"]))
        if not thumbs:
            return None
        pref = [t for t in thumbs if t.get("is_preferred")]
        return (pref[0] if pref else thumbs[0]).get("uri")
    except Exception:
        return None


def create_creative(account, video_id, cr):
    tmpl = C.load_yaml("launch_template.yaml")["creative_defaults"]
    video_data = {
        "video_id": video_id,
        "message": cr["primary_text"],
        "title": cr["headline"],
        "call_to_action": {
            "type": tmpl["call_to_action"],
            "value": {"link": C.LANDING_URL},
        },
    }
    thumb = video_thumbnail(video_id)
    if thumb:
        video_data["image_url"] = thumb   # Meta 要求影片縮圖
    story = {"page_id": C.PAGE_ID, "video_data": video_data}
    if C.INSTAGRAM_ID:
        story["instagram_actor_id"] = C.INSTAGRAM_ID
    params = {"name": cr.get("video") or cr.get("video_id"), "object_story_spec": story}
    if C.URL_TAGS:
        params["url_tags"] = C.URL_TAGS   # UTM 動態標籤(campaign/adset/ad 名自動帶入)
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

        delete_existing_campaigns(account, base)   # 清掉上次失敗的同名空殼
        clone_mode = bool(C.CLONE_SOURCE_ADSET)
        # clone 模式：ad set 帶自己的預算(ABO)，campaign 不設預算，objective 對齊來源
        obj = source_objective() if clone_mode else None
        camp_id = create_campaign(account, base, with_budget=not clone_mode, objective=obj)
        try:
            if clone_mode:
                print(f"  複製合規 ad set {C.CLONE_SOURCE_ADSET} → 繼承台灣廣告主聲明")
                adset_id = clone_compliant_adset(account, camp_id, base)
                # 複製現有贏家廣告(依名稱關鍵字，沿用 Live App 的 creative)→ 繞過 dev-mode
                n = copy_winner_ads(account, adset_id, C.WINNER_AD_KEYWORDS, base)
                print(f"  → 已複製 {n} 支贏家廣告到 ad set {adset_id}")
            else:
                adset_id = create_ad_set(account, camp_id, base, angle)
                for i, cr in enumerate(creatives, 1):
                    vid = cr.get("video_id") or upload_video(account, cr.get("video_url") or cr["video"])
                    creative_id = create_creative(account, vid, cr)
                    ad_id = create_ad(account, adset_id, creative_id, f"{base}-{i}")
                    print(f"  ✓ {base}-{i}  ad={ad_id}")
        except Exception:
            # 建到一半失敗 → 刪掉空 campaign，不留垃圾，再把錯誤丟出來
            try:
                Campaign(camp_id).api_delete()
                print(f"  (失敗，已刪除半成品 campaign {camp_id})")
            except Exception:
                pass
            raise
        print(f"  → campaign {camp_id} 建好 (PAUSED)。检查无误后用 Ads Manager 或 optimize 开 ACTIVE。")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--round", default="R1", help="本轮标记，如 R1")
    p.add_argument("--angles", default="", help="逗号分隔角度 key(空则跑 priority=1)")
    args = p.parse_args()
    only = [a.strip() for a in args.angles.split(",") if a.strip()] or None
    run(args.round, only)
