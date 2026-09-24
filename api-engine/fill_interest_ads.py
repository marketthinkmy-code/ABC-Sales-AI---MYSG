"""
把媒體庫已上傳的 16 支 hook 影片,平均分散塞進「興趣測試」campaign 底下那 8 支興趣 ad set。
每支 ad set 放 2 支影片(16 ÷ 8 = 2),全部 PAUSED。之後檢查無誤再手動/加步驟開 ACTIVE。

- 影片:引用既有 video_id(config/video_ads_16.json),文案用已確認的 16 份,不重新上傳。
- 目標 ad set:讀 FILL_CAMPAIGN_ID 這條 campaign 現有的 ad set(依 id 排序,穩定分配)。
- 建廣告邏輯沿用 launch_from_library.create_video_ad(縮圖 + object_story_spec + url_tags)。
- 可重跑:ad set 裡若已有同名廣告就跳過,不會重複建。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, PAGE_ID, LANDING_URL, PIXEL_ID …
     FILL_CAMPAIGN_ID(預設 = 剛建的興趣測試 T1), PER_ADSET(預設 2),
     ACTIVATE(預設 false), DRY_RUN(預設 true)
用法: DRY_RUN=false python fill_interest_ads.py
"""
import os, json
import config as C
import naming as N
import launch_from_library as LIB
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad

CAMP_ID = os.environ.get("FILL_CAMPAIGN_ID") or "120247254989860658"   # 興趣測試 · T1
PER_ADSET = int(os.environ.get("PER_ADSET") or 2)
ACTIVATE = (os.environ.get("ACTIVATE") or "false").strip().lower() == "true"
DATA = os.path.join(C.ROOT, "config", "video_ads_16.json")


def existing_ad_names(adset_id):
    try:
        return {a.get("name") for a in C.fb_retry(
            lambda: list(AdSet(adset_id).get_ads(fields=["name"], params={"limit": 200})))}
    except Exception:
        return set()


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    items = json.load(open(DATA, encoding="utf-8"))

    # 讀目標 campaign 的 ad set,依 id 排序(穩定),平均切成每組 PER_ADSET 支
    adsets = C.fb_retry(lambda: list(
        Campaign(CAMP_ID).get_ad_sets(fields=["id", "name"], params={"limit": 100})))
    adsets = sorted(adsets, key=lambda a: a["id"])
    if not adsets:
        raise SystemExit(f"campaign {CAMP_ID} 底下找不到 ad set。")

    # 依 ad set 數量把影片平均分:每組拿連續 PER_ADSET 支(不夠就少)
    plan = []   # [(adset, [videos])]
    idx = 0
    for a in adsets:
        chunk = items[idx: idx + PER_ADSET]
        idx += PER_ADSET
        plan.append((a, chunk))
    leftover = items[idx:]   # 若影片比「ad set×PER_ADSET」多,剩下的輪流補回去
    for j, e in enumerate(leftover):
        plan[j % len(plan)][1].append(e)

    print(f"[fill] campaign {CAMP_ID} · {len(adsets)} 支 ad set · {len(items)} 支影片 "
          f"· 每組 {PER_ADSET} 支 · ACTIVATE={ACTIVATE} · DRY_RUN={C.DRY_RUN}")
    for a, vids in plan:
        print(f"  {a.get('name','')[:34]:<34} ← {[e['name'] for e in vids]}")
    if C.DRY_RUN:
        print("  (DRY:只排組,未建。DRY_RUN=false 才真的塞。)")
        return

    n = 0
    for a, vids in plan:
        aset_id = a["id"]
        have = existing_ad_names(aset_id)
        for e in vids:
            name = N.ad_name("VID", e["num"], e["headline"])
            if name in have:
                print(f"     ⏭  已存在,跳過: {name}")
                continue
            try:
                ad_id = LIB.create_video_ad(account, aset_id, e["video_id"],
                                            e["primary_text"], e["headline"], name)
                n += 1
                print(f"     ✓ [{a.get('name','')[:16]}] {name}  ad={ad_id}")
            except Exception as ex:
                print(f"     ⚠️ {name} 失敗: {str(ex).replace(chr(10),' ')[:120]}")
    print(f"→ 已塞 {n} 支影片廣告進 {len(adsets)} 支興趣 ad set(全 PAUSED)。")
    if ACTIVATE and n:
        LIB.activate_all(CAMP_ID)


if __name__ == "__main__":
    run()
