"""
一次性：把「贏家廣告」的真實文案(primary_text / headline)整段 dump 出來，
並印出字數，方便對照要讓 AI 產線寫多長。

用法: python dump_copy.py
"""
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adcreative import AdCreative
import launch as L


def _body_title(creative_id):
    """從 creative 撈 body/title，優先看 object_story_spec 裡的 link_data/video_data。"""
    cr = AdCreative(creative_id).api_get(
        fields=["body", "title", "object_story_spec", "asset_feed_spec"])
    body = cr.get("body") or ""
    title = cr.get("title") or ""
    oss = cr.get("object_story_spec") or {}
    for key in ("link_data", "video_data"):
        d = oss.get(key) or {}
        body = body or d.get("message", "") or d.get("call_to_action", {}).get("value", {}).get("link_caption", "")
        title = title or d.get("name", "") or d.get("title", "")
    afs = cr.get("asset_feed_spec") or {}
    if not body and afs.get("bodies"):
        body = afs["bodies"][0].get("text", "")
    if not title and afs.get("titles"):
        title = afs["titles"][0].get("text", "")
    return body, title


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    winners = L.find_winner_ads(account, C.WINNER_AD_KEYWORDS)
    print("WINNER_COPY_DUMP_START")
    for w in winners:
        cid = w.get("creative_id")
        if not cid:
            print(f"\n===== {w['kw']} | ad={w['id']} (無 creative_id) =====")
            continue
        try:
            body, title = _body_title(cid)
        except Exception as e:
            print(f"\n===== {w['kw']} | ad={w['id']} 讀取失敗: {e} =====")
            continue
        print(f"\n===== 關鍵字「{w['kw']}」| ad={w['id']} =====")
        print(f"[標題 headline] ({len(title)} 字)\n{title}")
        print(f"[文案 primary_text] ({len(body)} 字)\n{body}")
        print(f"[行數] {len(body.splitlines())} 行")
    print("\nWINNER_COPY_DUMP_END")


if __name__ == "__main__":
    run()
