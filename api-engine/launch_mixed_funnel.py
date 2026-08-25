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


CREATIVE_FIELDS = ["object_story_spec", "asset_feed_spec",
                   "video_id", "image_hash", "image_url",
                   "effective_object_story_id"]


def _oss_item(cj):
    """從 creative 各種形狀萃出 video_id / image_hash + 文案。
    支援：object_story_spec.video_data/link_data、asset_feed_spec.videos/images、
    以及頂層 video_id/image_hash。"""
    cj = cj or {}
    oss = cj.get("object_story_spec") or {}
    vd = oss.get("video_data") or {}
    ld = oss.get("link_data") or {}
    afs = cj.get("asset_feed_spec") or {}
    afs_vids = afs.get("videos") or []
    afs_imgs = afs.get("images") or []

    # 文案：優先 object_story_spec，其次 asset_feed_spec 的 bodies/titles
    def _txt(*cands):
        for c in cands:
            if c:
                return c
        return ""
    body = _txt(vd.get("message"), ld.get("message"),
                (afs.get("bodies") or [{}])[0].get("text") if afs.get("bodies") else "")
    title = _txt(vd.get("title"), ld.get("name"),
                 (afs.get("titles") or [{}])[0].get("text") if afs.get("titles") else "")

    # video：object_story_spec → asset_feed_spec → 頂層
    vid = vd.get("video_id") or (afs_vids[0].get("video_id") if afs_vids else None) or cj.get("video_id")
    if vid:
        return {"kind": "video", "video_id": str(vid), "msg": body, "title": title}
    # image：link_data.image_hash → asset_feed_spec.images[].hash → 頂層
    ih = ld.get("image_hash") or (afs_imgs[0].get("hash") if afs_imgs else None) or cj.get("image_hash")
    if ih:
        return {"kind": "image", "image_hash": str(ih), "msg": body, "title": title}
    return None


_dbg_dumped = set()


def _cid(cr):
    """creative 欄位可能回 dict 或 SDK 物件,兩種都取得到 id。"""
    if not cr:
        return None
    if isinstance(cr, dict):
        return cr.get("id")
    try:
        return cr["id"]           # AbstractCrudObject 支援 index
    except Exception:
        pass
    return cr.get("id") if hasattr(cr, "get") else getattr(cr, "id", None)


def _creative_of(ad, dbg_key=None):
    cid = _cid(ad.get("creative"))
    if not cid:
        return None
    full = C.fb_retry(AdCreative(cid).api_get, fields=CREATIVE_FIELDS)
    item = _oss_item(full)
    # 每個池第一支對不到時,印出實際 creative 結構的鍵,方便定位
    if item is None and dbg_key and dbg_key not in _dbg_dumped:
        _dbg_dumped.add(dbg_key)
        try:
            d = full.export_all_data() if hasattr(full, "export_all_data") else dict(full)
        except Exception:
            d = dict(full)
        oss = d.get("object_story_spec") or {}
        afs = d.get("asset_feed_spec") or {}
        print(f"    [dbg {dbg_key}] creative keys={list(d.keys())} | "
              f"oss keys={list(oss.keys())} | afs keys={list(afs.keys())} | "
              f"video_id={d.get('video_id')} image_hash={d.get('image_hash')} "
              f"eff_post={d.get('effective_object_story_id')}")
    return item


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
        it = _creative_of(ad, dbg_key=f"camp:{camp_name[:8]}")
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


def _name_matches(nm, needle):
    """比對廣告名是否含 needle;若 needle 以數字結尾,要求後面不接數字,
    避免『M1Video 1』誤中 M1Video 10/11/12。"""
    if needle[-1].isdigit():
        return re.search(re.escape(needle) + r"(?!\d)", nm) is not None
    return needle in nm


def pool_winning(account, names):
    ads = list(C.fb_retry(account.get_ads,
                          fields=["name", "creative", "effective_status"],
                          params={"limit": 1000}))
    hits = [ad for ad in ads
            if any(_name_matches(ad.get("name") or "", w) for w in names)]
    print(f"  · 帳號共掃到 {len(ads)} 支廣告;名稱含 {names} 的 {len(hits)} 支")
    if not hits and ads:
        print(f"    （前 10 支廣告名樣本:{[ (a.get('name') or '')[:32] for a in ads[:10] ]}）")
    out, seen = [], set()
    for ad in hits:
        it = _creative_of(ad, dbg_key="winning")
        if it:
            key = it.get("video_id") or it.get("image_hash")
            if key and key not in seen:
                seen.add(key)
                it["src_name"] = ad.get("name", "")
                out.append(it)
    return out


def make_mix_adset(account, camp, name):
    """從零建 ABO ad set,建立時就帶【新 pixel + CompleteRegistration】。
    不用 clone 贏家再改 pixel——Meta 不准改已發布 ad set 的 pixel/event。
    台灣合規(廣告主聲明)改由 regional_regulated_categories + DSA 參數在建立時帶上。"""
    params = {
        "name": name,
        "campaign_id": camp,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "daily_budget": C.to_minor(LS.ADSET_BUDGET),   # ABO:預算在 ad set
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",      # 自動出價,不必帶 bid amount
        "promoted_object": {"pixel_id": PIXEL, "custom_event_type": EVENT},
        "targeting": LS.targeting(),                    # 台灣·30-55·繁中(22)·手動版位
        "status": "PAUSED",
    }
    # 台灣法規:含台灣地區必須聲明 regulated category + 廣告主/付款方。
    params["regional_regulated_categories"] = ["TAIWAN_UNIVERSAL"]
    if C.DSA_BENEFICIARY:
        params["dsa_beneficiary"] = C.DSA_BENEFICIARY
    if C.DSA_PAYOR:
        params["dsa_payor"] = C.DSA_PAYOR
    return C.fb_retry(account.create_ad_set, params=params)["id"]


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
    cname = f"{N.campaign_name('Video')} · {SUFFIX}"
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
        # ABO:預算在 ad set,bid_strategy 也放 ad set(campaign 沒預算不能設)
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}（{LS.ADSET_BUDGET:.0f}/組 · PAUSED）")

    total = sum(len(g) for g in groups)
    n = 0
    for gi, g in enumerate(groups, 1):
        adset_id = make_mix_adset(account, camp, f"{N.adset_name(LS.targeting())} · 組{gi}")
        print(f"  ── 組{gi} ad set {adset_id}（台灣·30-55·繁中·手動·pixel {PIXEL[-6:]}·CompleteRegistration）")
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
