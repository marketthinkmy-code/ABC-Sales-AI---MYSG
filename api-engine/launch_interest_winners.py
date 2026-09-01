"""
興趣定向 · Winners 放大：開一條新 campaign,8 個『單一興趣』ad set,每個都放贏家素材。
用來測『哪個 ICP 興趣受眾』最會轉,順便把贏家素材放大到新受眾。

- campaign:ABO,全 PAUSED(先 staged,人工確認後才開)。
- 每個 ad set:台灣 · 30-55 · 繁中(22) · 手動版位 · 一個 ICP 興趣(flexible_spec)·
  advantage_audience=0(讓興趣定向真的生效,不被 Advantage+ 外擴蓋掉)·
  promoted_object=一般 pixel + CompleteRegistration · 台灣合規(受益人/付款人=商家)。
- 廣告:直接『引用』贏家現有 creative_id(M1Video 9/1/8),不建新貼文,沿用原本落地頁。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, INTEREST_PIXEL(選填,預設一般 pixel),
     INTEREST_ADSET_BUDGET(預設 1000), WINNER_NAMES(選填), DRY_RUN(預設 true)
"""
import os, re, time
import config as C
import launch as L
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.ad import Ad

PIXEL = os.environ.get("INTEREST_PIXEL") or C.PIXEL_ID     # 一般/舊 pixel(贏家原本的漏斗)
EVENT = os.environ.get("INTEREST_EVENT") or "COMPLETE_REGISTRATION"
BUDGET = float(os.environ.get("INTEREST_ADSET_BUDGET") or 1000)
WINNER_NAMES = [s.strip() for s in (os.environ.get("WINNER_NAMES")
                or "M1Video 9,M1Video 1,M1Video 8").split(",") if s.strip()]
PACE = float(os.environ.get("PACE_SEC") or 3)

# 8 個單一興趣 ad set(名稱, 興趣 id)——都是貼 ICP 的商業/店家/美業意圖
INTERESTS = [
    ("中小企業", ["6003136069408"]),        # 中小型企業
    ("企業家",   ["6003371567474"]),        # 企業家
    ("新創公司", ["6003325004380"]),        # 新創公司
    ("電子商務", ["6003221485467"]),        # 電子商務(零售)
    ("Shopify店家", ["6003230166788"]),     # Shopify
    ("數位行銷", ["6003127206524"]),        # 數位行銷
    ("社群行銷", ["6003389760112"]),        # 社群媒體行銷
    ("美業沙龍", ["6003088846792"]),        # 美容沙龍
]


def _match(nm):
    for w in WINNER_NAMES:
        if w and w[-1].isdigit():
            if re.search(re.escape(w) + r"(?!\d)", nm):
                return w
        elif w in nm:
            return w
    return None


def winner_creatives(account):
    """依名稱找贏家廣告,取其 creative_id(去重),回 [(kw, creative_id)]。"""
    ads = list(C.fb_retry(account.get_ads, fields=["name", "creative"], params={"limit": 1000}))
    out, seen = [], set()
    for want in WINNER_NAMES:
        for ad in ads:
            if _match(ad.get("name", "")) != want:
                continue
            cr = ad.get("creative") or {}
            cid = cr.get("id") if isinstance(cr, dict) else (cr["id"] if cr else None)
            if cid and cid not in seen:
                seen.add(cid)
                out.append((want, cid))
                break
    return out


def interest_targeting(ids):
    return {
        "geo_locations": {"countries": ["TW"]},
        "age_min": 30, "age_max": 55,
        "locales": [22],
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "facebook_reels", "story"],
        "instagram_positions": ["stream", "reels", "story"],
        "flexible_spec": [{"interests": [{"id": i} for i in ids]}],
        "targeting_automation": {"advantage_audience": 0},   # 讓興趣定向生效
    }


def make_interest_adset(account, camp, name, ids):
    params = {
        "name": name, "campaign_id": camp,
        "billing_event": "IMPRESSIONS", "optimization_goal": "OFFSITE_CONVERSIONS",
        "daily_budget": C.to_minor(BUDGET),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "promoted_object": {"pixel_id": PIXEL, "custom_event_type": EVENT},
        "targeting": interest_targeting(ids),
        "status": "PAUSED",
        "regional_regulated_categories": ["TAIWAN_UNIVERSAL"],
        "regional_regulation_identities": {
            "taiwan_universal_beneficiary": C.BUSINESS_ID,
            "taiwan_universal_payer": C.BUSINESS_ID,
        },
    }
    return C.fb_retry(account.create_ad_set, params=params)["id"]


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    wins = winner_creatives(account)
    print(f"[興趣×Winners] pixel={PIXEL} event={EVENT} · 每組 {BUDGET:.0f}/日 · DRY_RUN={C.DRY_RUN}")
    print(f"  贏家素材(引用 creative_id):{[(k, c) for k, c in wins]}")
    print(f"  8 個興趣 ad set:{[lbl for lbl, _ in INTERESTS]}")
    if not wins:
        print("  ⚠️ 找不到贏家素材(檢查 WINNER_NAMES)。")
    if C.DRY_RUN:
        for lbl, ids in INTERESTS:
            print(f"    · {lbl}({','.join(ids)}) ← {len(wins)} 支贏家")
        print("  （DRY:只排組,未建）")
        return
    if not wins:
        raise SystemExit("沒有贏家素材,停手。")

    L.ensure_page_advertiser()
    cname = f"{N.campaign_name('Video')} · 興趣定向 · Winners放大"
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}（{BUDGET:.0f}/組 · PAUSED）")

    n_ad = 0
    for gi, (lbl, ids) in enumerate(INTERESTS, 1):
        try:
            aset = make_interest_adset(account, camp, f"興趣 · {lbl}", ids)
        except Exception as e:
            print(f"  ⚠️ ad set「{lbl}」建立失敗: {str(e).replace(chr(10),' ')[:120]}")
            continue
        print(f"  ── {lbl} ad set {aset}（興趣 {','.join(ids)} · pixel {PIXEL[-6:]}）")
        for kw, cid in wins:
            nm = N.ad_name("WIN", gi * 10, re.sub(r"\s+", "", kw))
            try:
                ad = C.fb_retry(account.create_ad, params={
                    "name": nm, "adset_id": aset,
                    "creative": {"creative_id": cid}, "status": "PAUSED"})
                n_ad += 1
                print(f"     ✓ 贏家 {kw} ad={ad['id']}")
            except Exception as e:
                print(f"     ⚠️ 贏家 {kw} 失敗: {str(e).replace(chr(10),' ')[:100]}")
            time.sleep(PACE)
        time.sleep(PACE)
    print(f"→ 已建 8 個興趣 ad set · {n_ad} 支贏家廣告（全 PAUSED,未 activate）。")


if __name__ == "__main__":
    run()
