"""
撈出帳號的 Page ID / Pixel ID / 現有影片 ID，方便填 launch 設定。
此帳號 MCP 被鎖，無法用 MCP 查，所以用 API 直接列出來。

用法:
  python discover.py
"""
import config as C
from facebook_business.adobjects.adaccount import AdAccount


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    print(f"[discover] 帳號 {C.AD_ACCOUNT_ID}\n")

    print("=== 可投放的 Facebook 粉專 (PAGE_ID) ===")
    found_page = False
    try:
        for p in account.get_promote_pages(fields=["id", "name"]):
            print(f"  PAGE_ID={p['id']}  |  {p.get('name','')}")
            found_page = True
    except Exception as e:
        print(f"  (promote_pages 讀取失敗: {e})")
    # 退路：從現有廣告的 creative 反查 page_id(最可靠，因為現在的廣告就綁著它)
    if not found_page:
        print("  promote_pages 為空，改從現有廣告 creative 反查:")
        try:
            seen = set()
            for cr in account.get_ad_creatives(fields=["object_story_spec"], params={"limit": 25}):
                spec = cr.get("object_story_spec") or {}
                pid = spec.get("page_id")
                if pid and pid not in seen:
                    seen.add(pid)
                    print(f"  PAGE_ID={pid}  (來自現有廣告)")
            if not seen:
                print("  (現有廣告也查不到 page_id)")
        except Exception as e:
            print(f"  (creative 反查失敗: {e})")

    print("\n=== Pixel / 資料集 (PIXEL_ID) ===")
    try:
        for px in account.get_ads_pixels(fields=["id", "name"]):
            print(f"  PIXEL_ID={px['id']}  |  {px.get('name','')}")
    except Exception as e:
        print(f"  (讀取失敗: {e})")

    print("\n=== 現有影片 (可直接當素材, VIDEO_ID) — 最近 15 支 ===")
    try:
        for v in account.get_ad_videos(fields=["id", "title"], params={"limit": 15}):
            print(f"  video_id={v['id']}  |  {v.get('title','(無標題)')}")
    except Exception as e:
        print(f"  (讀取失敗: {e})")

    print("\n=== Instagram 帳號 (INSTAGRAM_ID, 選填) ===")
    try:
        for ig in account.get_instagram_accounts(fields=["id", "username"]):
            print(f"  INSTAGRAM_ID={ig['id']}  |  @{ig.get('username','')}")
    except Exception as e:
        print(f"  (讀取失敗或無: {e})")

    print("\n=== 現有廣告組合的合規欄位(台灣 advertiser 聲明用) ===")
    try:
        from facebook_business.adobjects.campaign import Campaign
        fields = ["id", "name", "regional_regulated_categories",
                  "dsa_beneficiary", "dsa_payor", "promoted_object", "targeting"]
        shown = 0
        for camp in account.get_campaigns(fields=["id", "effective_status"], params={"limit": 30}):
            if camp.get("effective_status") != "ACTIVE":
                continue
            for aset in Campaign(camp["id"]).get_ad_sets(fields=fields, params={"limit": 2}):
                print(f"  adset {aset.get('id')} | {aset.get('name','')[:30]}")
                print(f"    regional_regulated_categories = {aset.get('regional_regulated_categories')}")
                print(f"    dsa_beneficiary = {aset.get('dsa_beneficiary')}")
                print(f"    dsa_payor       = {aset.get('dsa_payor')}")
                tgt = aset.get('targeting') or {}
                print(f"    targeting.keys  = {list(tgt.keys())}")
                shown += 1
                break
            if shown >= 2:
                break
        if not shown:
            print("  (找不到 ACTIVE 廣告組合)")
    except Exception as e:
        print(f"  (讀取失敗: {e})")

    print("\n填好上面的值到 GitHub Secrets 或 .env，就能跑 launch.py 自動上廣告。")


if __name__ == "__main__":
    run()
