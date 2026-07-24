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
    try:
        for p in account.get_promote_pages(fields=["id", "name"]):
            print(f"  PAGE_ID={p['id']}  |  {p.get('name','')}")
    except Exception as e:
        print(f"  (讀取失敗: {e})")

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

    print("\n填好上面的值到 GitHub Secrets 或 .env，就能跑 launch.py 自動上廣告。")


if __name__ == "__main__":
    run()
