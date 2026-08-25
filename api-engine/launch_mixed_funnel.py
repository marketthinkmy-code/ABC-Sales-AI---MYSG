"""
預約型・週三 混搭 funnel：一條新 ABO campaign,每個 ad set 混 3 支廣告
（1 winning ＋ 1 新影片 ＋ 1 單圖），沿用現有素材與文案,只換 pixel + landing URL。

- 素材來源(重用帳號現有 creative 的 video_id / image_hash / 文案,不重上傳):
    winning：名稱含 M1Video 9 / M1Video 1 / M1Video 8 的現有廣告
    新影片：campaign「AI獲客 · Video · 8月20號2026」裡的影片
    單圖：campaign「AI獲客 · Image · 8月19號2026」裡的圖
- 每個 ad set = 1 新影片(主) ＋ 1 winning(輪流) ＋ 1 單圖(輪流)。
- ad set：台灣 · 30-55 · 繁中 locale 22 · 手動版位 · ABO 500/日 · clone 贏家合規；
          promoted_object 覆寫成【新 pixel + CompleteRegistration】。
- 廣告連結/CTA 指向【新 landing URL】(C.LANDING_URL)；UTM(url_tags)照舊、不加預約字樣。
- 全部建成 PAUSED,不 activate（先把 post 放著）。DRY_RUN=true 只印配對。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, INSTAGRAM_ID, OBJECTIVE,
     MIX_PIXEL_ID, MIX_EVENT(預設 COMPLETE_REGISTRATION), LANDING_URL(新),
     IMAGE_ADSET_BUDGET(=500), MIX_VIDEO_CAMPAIGN, MIX_IMAGE_CAMPAIGN, MAX_ADSETS(選填)
"""
import os, re, time
import config as C
import launch as L
import naming as N
import launch_static_ads as LS
import video_pipeline as VP
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.campaign import Campaign

PIXEL = os.environ["MIX_PIXEL_ID"]
EVENT = os.environ.get("MIX_EVENT") or "COMPLETE_REGISTRATION"
WINNING = [s.strip() for s in (os.environ.get("MIX_WINNING") or "M1Video 9,M1Video 1,M1Video 8").split(",")]
VIDEO_CAMP = os.environ.get("MIX_VIDEO_CAMPAIGN") or "AI獲客 · Video · 8月20號2026"
IMAGE_CAMP = os.environ.get("MIX_IMAGE_CAMPAIGN") or "AI獲客 · Image · 8月19號2026"
SUFFIX = os.environ.get("MIX_SUFFIX") or "預約型 · 週三"
MAX_ADSETS = int(os.environ.get("MAX_ADSETS") or 0)   # 0 = 用完全部新影片
PACE = float(os.environ.get("PACE_SEC") or 3)


def _oss_item(creative_json):
    oss = (creative_json or {}).get("object_story_spec") or {}
    vd = oss.get("video_data")
    if vd and vd.get("video_id"):
        return {"kind": "video", "video_id": vd["video_id"],
                "msg": vd.get("message") or "", "title": vd.get("title") or ""}
    ld = oss.get("link_data")
    if ld and ld.get("image_hash"):
        return {"kind": "image", "image_hash": ld["image_hash"],
                "msg": ld.get("message") or "", "title": ld.get("name") or ""}
    return None


def _creative_of(ad):
    cr = ad.get("creative") or {}
    cid = cr.get("id") if isinstance(cr, dict) else None
    if not cid:
        return None
    full = C.fb_retry(AdCreative(cid).api_get, fields=["object_story_spec"])
    return _oss_item(full)


def _all_campaigns(account):
    camps = list(C.fb_retry(account.get_campaigns, fields=["id", "name"],
                            params={"limit": 500}))
    print(f"  · 帳號共掃到 {len(camps)} 條 campaign")
    return camps


def pool_from_campaign(account, camp_name, camps=None):
    camps = camps if camps is not None else _all_campaigns(account)
    cid = None
    for c in camps:
        if (c.get("name") or "") == camp_name:
            cid = c["id"]
            break
    if not cid:
        # 名稱對不到就印出含關鍵字的候選,方便修正
        kw = camp_name.split("·")[0].strip()[:4] or camp_name[:4]
        near = [c.get("name", "") for c in camps if kw and kw in (c.get("name") or "")]
        print(f"  ⚠️ 找不到 campaign「{camp_name}」;含「{kw}」的有: {near[:8]}")
        return []
    ads = list(C.fb_retry(Campaign(cid).get_ads, fields=["name", "creative"],
                          params={"limit": 200}))
    out, seen, no_cr = [], set(), 0
    for ad in ads:
        it = _creative_of(ad)
        if not it:
            no_cr += 1
            continue
        key = it.get("video_id") or it.get("image_hash")
        if key and key not in seen:
            seen.add(key)
            it["src_name"] = ad.get("name", "")
            out.append(it)
    print(f"  · campaign「{camp_name}」→ {len(ads)} 支廣告 / 可用素材 {len(out)}"
          f"（無 video_id/image_hash 的 {no_cr} 支）")
    return out


def pool_winning(account, names):
    ads = list(C.fb_retry(account.get_ads,
                          fields=["name", "creative", "effective_status"],
                          params={"limit": 1000}))
    hits = [ad for ad in ads if any(w in (ad.get("name") or "") for w in names)]
    print(f"  · 帳號共掃到 {len(ads)} 支廣告;名稱含 {names} 的 {len(hits)} 支")
    if not hits and ads:
        print(f"    （前 10 支廣告名樣本:{[ (a.get('name') or '')[:32] for a in ads[:10] ]}）")
    out, seen = [], set()
    for ad in hits:
        it = _creative_of(ad)
        if it:
            key = it.get("video_id") or it.get("image_hash")
            if key and key not in seen:
                seen.add(key)
                it["src_name"] = ad.get("name", "")
                out.append(it)
    return out


def make_ad(account, adset_id, item, name):
    if item["kind"] == "video":
        return C.fb_retry(VP.create_video_ad, account, adset_id, item["video_id"],
                          VP.thumbnail(item["video_id"]), item["msg"], item["title"], name)
    return C.fb_retry(LS.create_image_ad, account, adset_id, item["image_hash"],
                      item["msg"], item["title"], name)


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    camps = _all_campaigns(account)
    win = pool_winning(account, WINNING)
    vids = pool_from_campaign(account, VIDEO_CAMP, camps)
    imgs = pool_from_campaign(account, IMAGE_CAMP, camps)
    print(f"[mix] winning {len(win)} · 新影片 {len(vids)} · 單圖 {len(imgs)} | pixel={PIXEL} event={EVENT} | DRY_RUN={C.DRY_RUN}")
    print(f"      landing = {C.LANDING_URL}")
    if not (win and vids and imgs):
        print("  ⚠️ 有一個池是空的,無法混搭。檢查上面找到的數量與 campaign 名稱。")
        # 繼續印出各池方便除錯
    n_sets = len(vids) if MAX_ADSETS == 0 else min(MAX_ADSETS, len(vids))
    groups = []
    for i in range(n_sets):
        g = [vids[i]]
        if win:
            g.append(win[i % len(win)])
        if imgs:
            g.append(imgs[i % len(imgs)])
        groups.append(g)
    print(f"  → {len(groups)} 個 ad set（每組 = 1 新影片 ＋ 1 winning ＋ 1 單圖）")
    for gi, g in enumerate(groups, 1):
        line = " ｜ ".join(f"{x['kind']}:{(x.get('src_name') or x.get('title') or '')[:20]}" for x in g)
        print(f"    組{gi}: {line}")
    if C.DRY_RUN:
        print("  （DRY:只讀+排組,未建）")
        return
    if not (win and vids and imgs):
        raise SystemExit("素材池不完整,停手（避免建出殘缺 campaign）。")

    L.ensure_page_advertiser()
    winners = C.fb_retry(L.find_winner_ads, account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到合規來源(贏家 ad set)。")
    src = winners[0]["adset_id"]
    cname = f"{N.campaign_name('Video')} · {SUFFIX}"
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}（{LS.ADSET_BUDGET:.0f}/組 · PAUSED）")

    total = sum(len(g) for g in groups)
    n = 0
    for gi, g in enumerate(groups, 1):
        adset_id = LS.make_abo_adset(account, camp, src, f"組{gi}")
        # 覆寫 promoted_object → 新 pixel + CompleteRegistration
        C.fb_retry(AdSet(adset_id).api_update, params={
            "promoted_object": {"pixel_id": PIXEL, "custom_event_type": EVENT}})
        print(f"  ── 組{gi} ad set {adset_id}（台灣·30-55·繁中·手動·pixel {PIXEL[-6:]}）")
        for j, item in enumerate(g, 1):
            nm = N.ad_name(item["kind"].upper(), gi * 10 + j,
                           re.sub(r"\s+", "", item.get("title") or item.get("src_name") or "")[:20])
            try:
                ad_id = make_ad(account, adset_id, item, nm)
                n += 1
                print(f"     ✓ {item['kind']} {nm} ad={ad_id}")
            except Exception as e:
                print(f"     ⚠️ {item['kind']} {nm} 失敗: {e}")
            time.sleep(PACE)
        time.sleep(PACE * 2)
    print(f"→ 已建 {n}/{total} 支混搭廣告於 ABO campaign（全 PAUSED，未 activate）。")
    print("  ⓘ 這條是『預約型・週三』：新 pixel + 新 landing，週二那條完全沒動。")


if __name__ == "__main__":
    run()
