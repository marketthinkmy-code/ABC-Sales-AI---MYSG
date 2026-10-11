"""
復活賽 campaign —— 專放「以前沒好好測過」的舊 creative,引用它們現有的 creative_id
(不重做素材),每組 1 支影片 + 1 張單圖 mix & match,興趣定向,全 PAUSED。

- 配對見 GROUPS:每組一個興趣 + 一支影片關鍵字 + 一張單圖關鍵字。
- 腳本掃帳號現有廣告,用名稱關鍵字找到對應 creative_id。
- ad set 沿用已驗證的 make_interest_adset(台灣合規/人口/版位/pixel+CompleteRegistration)。
- 廣告直接 creative:{creative_id} 引用,不建新貼文。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, INTEREST_ADSET_BUDGET(預設 400), DRY_RUN
用法: DRY_RUN=false python launch_revival.py
"""
import os, re, time
import config as C
import naming as N
import launch as L
import launch_interest_winners as W
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign

# 每組:(興趣標籤, 興趣id, 影片名稱關鍵字, 單圖名稱關鍵字)
GROUPS = [
    ("美業沙龍", "6003088846792", "先別急著請人",       "Ad_TW_Aesthetics"),
    ("電子商務", "6003221485467", "一半在半路被吃掉",   "Ad_TW_LiveCommerce"),
    ("中小企業", "6003136069408", "別管這些人",         "Ad_TW_Insurance"),
    ("企業家",   "6003371567474", "這則你不用回",       "Ad_TW_Wedding"),
    ("數位行銷", "6003127206524", "你回得完嗎",         "#153"),
    ("新創公司", "6003325004380", "還差這個AI員工",     "Ad_TW_CramSchool"),
]
PACE = float(os.environ.get("PACE_SEC") or 3)


def _cid(cr):
    if not cr:
        return None
    try:
        return cr["id"]
    except Exception:
        return cr.get("id") if hasattr(cr, "get") else None


def scan_creatives(account):
    """回 [(name, creative_id)]。"""
    out = []
    for a in C.fb_retry(account.get_ads, fields=["name", "creative"], params={"limit": 2000}):
        out.append(((a.get("name") or ""), _cid(a.get("creative"))))
    return out


def find_cid(ads, kw):
    """找名稱含 kw 的廣告,回 (creative_id, 完整名稱)。取第一個有 creative 的。"""
    for nm, cid in ads:
        if kw in nm and cid:
            return cid, nm
    return None, None


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    ads = scan_creatives(account)
    cname = f"{N.campaign_name('Video')} · 復活賽 · T1"

    plan = []
    for lbl, iid, vkw, ikw in GROUPS:
        vcid, vnm = find_cid(ads, vkw)
        icid, inm = find_cid(ads, ikw)
        plan.append({"lbl": lbl, "iid": iid, "vkw": vkw, "ikw": ikw,
                     "vcid": vcid, "vnm": vnm, "icid": icid, "inm": inm})

    print(f"[復活賽] 掃到 {len(ads)} 支現有廣告 · 每組 {W.BUDGET:.0f}/日 · DRY_RUN={C.DRY_RUN}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / PAUSED）")
    for p in plan:
        print(f"  ── 興趣 {p['lbl']}")
        print(f"       影片「{p['vkw']}」→ {'✓ '+p['vnm'][:40] if p['vcid'] else '✗ 找不到'}")
        print(f"       單圖「{p['ikw']}」→ {'✓ '+p['inm'][:40] if p['icid'] else '✗ 找不到'}")
    if C.DRY_RUN:
        print("  (DRY:只配對,未建。DRY_RUN=false 才真的建。)")
        return

    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    n = 0
    for gi, p in enumerate(plan, 1):
        try:
            aset = W.make_interest_adset(account, camp, f"興趣 · {p['lbl']}", [p["iid"]])
        except Exception as e:
            print(f"  ⚠️ [{p['lbl']}] ad set 失敗: {str(e).replace(chr(10),' ')[:120]}")
            continue
        print(f"  ── {p['lbl']} ad set {aset}")
        for tag, cid, kw in (("VID", p["vcid"], p["vkw"]), ("IMG", p["icid"], p["ikw"])):
            if not cid:
                print(f"     ⏭ {tag}「{kw}」無 creative,跳過")
                continue
            nm = N.ad_name("REV", gi, f"{p['lbl']}·{kw}")
            try:
                ad = C.fb_retry(account.create_ad, params={
                    "name": nm, "adset_id": aset,
                    "creative": {"creative_id": cid}, "status": "PAUSED"})
                n += 1
                print(f"     ✓ {tag}「{kw}」(引用 {cid}) → ad {ad['id']}")
            except Exception as e:
                print(f"     ⚠️ {tag}「{kw}」失敗: {str(e).replace(chr(10),' ')[:100]}")
            time.sleep(PACE)
        time.sleep(PACE)
    print(f"→ 已建 {n} 支復活廣告於 {len(plan)} 個興趣 ad set（全 PAUSED）。")


if __name__ == "__main__":
    run()
