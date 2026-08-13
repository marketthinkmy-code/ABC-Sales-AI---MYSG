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


def ensure_page_advertiser():
    """把 token 的系統使用者授予 Page 的 ADVERTISE 權限(建廣告必需)。best-effort。"""
    from facebook_business.adobjects.user import User
    from facebook_business.adobjects.page import Page
    try:
        su_id = User("me").api_get(fields=["id"])["id"]
        Page(C.PAGE_ID).create_assigned_user(params={
            "user": su_id, "tasks": ["ADVERTISE"], "business": C.BUSINESS_ID})
        print(f"  ✓ 已授予系統使用者 {su_id} 對 Page {C.PAGE_ID} 的 ADVERTISE 權限")
        return True
    except Exception as e:
        print(f"  ⚠️ 自動授予 Page 權限失敗(可能 token 權限不足): {e}")
        return False


def find_winner_ads(account, keywords):
    """依名稱關鍵字找現有贏家廣告，回傳 [{id,name,adset_id,creative_id,kw}]。"""
    ads = [{"id": a["id"], "name": a.get("name", ""), "adset_id": a.get("adset_id"),
            "creative_id": (a.get("creative") or {}).get("id")}
           for a in account.get_ads(fields=["id", "name", "adset_id", "creative"],
                                     params={"limit": 1000})]
    print(f"  掃到 {len(ads)} 支現有廣告")
    picked = []
    for kw in keywords:
        m = next((a for a in ads if kw in a["name"]), None)
        if m:
            picked.append({**m, "kw": kw})
        else:
            print(f"  ⚠️ 找不到名稱含「{kw}」的現有廣告")
    return picked


def copy_source_campaign(account, name, src_adset_id):
    """複製指定 ad set 的母 campaign(空殼，deep_copy=False)，繼承 objective/buying 設定。"""
    src_camp = AdSet(src_adset_id).api_get(fields=["campaign_id"])["campaign_id"]
    resp = Campaign(src_camp).create_copy(params={"deep_copy": False, "status_option": "PAUSED"})
    new_id = (resp.get("copied_campaign_id") or resp.get("id")) if hasattr(resp, "get") else None
    if not new_id:
        new_id = resp["copied_campaign_id"]
    Campaign(new_id).api_update(params={"name": name, "status": "PAUSED"})
    return new_id


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
        params["daily_budget"] = C.to_minor(C.START_DAILY_BUDGET)
    else:
        # ABO：預算+出價策略在 ad set 層；campaign 不設 bid_strategy(否則 Meta 要求 campaign budget)
        params["is_adset_budget_sharing_enabled"] = False
    return account.create_campaign(params=params)["id"]


def clone_compliant_adset(account, campaign_id, name, src_adset_id):
    """複製指定的已合規 ad set(繼承台灣廣告主聲明)到新 campaign，清掉舊廣告，回傳新 ad set id。"""
    budget = C.START_DAILY_BUDGET
    resp = AdSet(src_adset_id).create_copy(params={
        "campaign_id": campaign_id,
        "status_option": "PAUSED",
    })
    # 取新 ad set id(SDK 回傳形狀可能不同，逐一嘗試)
    new_id = (resp.get("copied_adset_id") or resp.get("id")
              or (resp.get("ad_object_ids") or {}).get("adset")) if hasattr(resp, "get") else None
    if not new_id:
        new_id = resp["copied_adset_id"]
    new_aset = AdSet(new_id)
    new_aset.api_update(params={"name": name, "status": "PAUSED"})
    # 預算：若母 campaign 是 CBO，ad set 不能設預算 → 失敗就略過(沿用來源設定)
    try:
        new_aset.api_update(params={"daily_budget": C.to_minor(budget)})
    except Exception:
        pass
    # 刪掉複製過來的舊廣告，改放我們的贏家
    for ad in new_aset.get_ads(fields=["id"]):
        try:
            Ad(ad["id"]).api_delete()
        except Exception:
            pass
    return new_id


def copy_winner_ads(account, adset_id, winners, base):
    """在新 ad set 建廣告，直接『引用』贏家的現有 creative_id → 不建新貼文，
    繞過 dev-mode 與 Page 權限。每支獨立 try/except。"""
    count = 0
    for w in winners:
        kw = w["kw"]
        cid = w.get("creative_id")
        if not cid:
            try:
                cid = (Ad(w["id"]).api_get(fields=["creative"]).get("creative") or {}).get("id")
            except Exception:
                cid = None
        if not cid:
            print(f"  ⚠️ 贏家「{kw}」取不到 creative_id，跳過")
            continue
        try:
            new = account.create_ad(params={
                "name": f"{base} | {kw}",
                "adset_id": adset_id,
                "creative": {"creative_id": cid},
                "status": "PAUSED",
            })
            count += 1
            print(f"  ✓ 建贏家「{kw}」(引用 creative {cid}) → ad {new['id']}")
        except Exception as e:
            print(f"  ⚠️ 贏家「{kw}」建廣告失敗，跳過: {e}")
    return count


def create_ad_set(account, campaign_id, name, angle):
    # 受眾/地區來自 config(markets.yaml 的市場區塊)。
    countries = C.GEO_COUNTRIES
    targeting = {
        "geo_locations": {"countries": countries},
        "age_min": C.AGE_MIN,
        "age_max": C.AGE_MAX,
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
    _apply_regional_compliance(params, countries)
    return account.create_ad_set(params=params)["id"]


def _apply_regional_compliance(params, countries):
    """依市場補上強制法規欄位。
    🇸🇬 SG(2025-05-27 起):regional_regulated_categories=SINGAPORE_UNIVERSAL
        + regional_regulation_identities(受益人/付款人 = 已驗證 business id)。
        ⚠️ 上線前用 DRY_RUN 之後的第一次真建驗證 Marketing API 是否接受這兩個欄位;
        若被擋,退回用 ads_create_ad 的 adset_spec 內聯建 ad set(見 SETUP)。
    🇹🇼 TW:沿用文字聲明(本專案 MY/SG 用不到)。
    """
    if C.REGIONAL_REGULATED_CATEGORIES:
        params["regional_regulated_categories"] = C.REGIONAL_REGULATED_CATEGORIES
        if "SINGAPORE_UNIVERSAL" in C.REGIONAL_REGULATED_CATEGORIES and C.DSA_BENEFICIARY_ID:
            params["regional_regulation_identities"] = {
                "singapore_universal_beneficiary": C.DSA_BENEFICIARY_ID,
                "singapore_universal_payer": C.DSA_PAYER_ID or C.DSA_BENEFICIARY_ID,
            }
    elif "TW" in countries:
        params["regional_regulated_categories"] = ["TAIWAN_UNIVERSAL"]
    if C.DSA_BENEFICIARY:
        params["dsa_beneficiary"] = C.DSA_BENEFICIARY
    if C.DSA_PAYOR:
        params["dsa_payor"] = C.DSA_PAYOR


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
        if clone_mode:
            ensure_page_advertiser()   # 先確保有 Page 建廣告權限
            # 先找贏家廣告，用「第一支贏家的母 ad set/campaign」當合規容器 →
            # objective 一定跟贏家一致，複製廣告不會 mismatch。
            winners = find_winner_ads(account, C.WINNER_AD_KEYWORDS)
            if not winners:
                raise SystemExit("找不到任何贏家廣告(關鍵字對不上)，請檢查 WINNER_AD_KEYWORDS。")
            src_adset = winners[0]["adset_id"]
            print(f"  以贏家「{winners[0]['kw']}」的 ad set {src_adset} 為合規來源")
            camp_id = copy_source_campaign(account, base, src_adset)
        else:
            camp_id = create_campaign(account, base, with_budget=True)
        try:
            if clone_mode:
                adset_id = clone_compliant_adset(account, camp_id, base, src_adset)
                print(f"  複製合規 ad set → 繼承台灣廣告主聲明；開始複製贏家廣告")
                n = copy_winner_ads(account, adset_id, winners, base)
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
