"""
新測試 campaign · 興趣定向 —— 開一條全新的 ABO campaign,專門拿來『大量測試新廣告』。
底下每個 ICP 興趣各一支 ad set(單一興趣賽馬),之後把新素材直接塞進這些 ad set。

跟 launch_interest_winners 共用同一套『已驗證』的合規建法:
  - ad set 從零建(make_interest_adset):台灣 · 30-55 · 繁中(22) · 手動版位
    (= 你之前的那個模樣) · 單一興趣 flexible_spec · advantage_audience=0(讓興趣生效)·
    promoted_object = pixel + CompleteRegistration · 台灣合規(受益人/付款人 = 商家)。
  - 種子廣告:預設不放(SEED_WINNERS=false)—— 空 ad set,等你倒新測試廣告進來。
    想先放贏家素材當對照組就設 SEED_WINNERS=true。

跟 Winners 放大版的差別只有『用途/命名』:這條是測試場,命名帶「測試」。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, INTEREST_PIXEL(選填), INTEREST_EVENT(選填),
     INTEREST_ADSET_BUDGET(預設 300), INTEREST_JSON(選填,整包覆蓋興趣清單),
     SEED_WINNERS(預設 false), WINNER_NAMES(選填), DRY_RUN(預設 true)
用法:
  DRY_RUN=true  python launch_interest_test.py --round T1
  DRY_RUN=false python launch_interest_test.py --round T1   # 真的建(仍 PAUSED)
"""
import os, re, json, time, argparse
import config as C
import launch as L
import naming as N
import launch_interest_winners as W
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign

SEED_WINNERS = (os.environ.get("SEED_WINNERS") or "false").strip().lower() == "true"


def _interests():
    """興趣清單:預設用 Winners 版那 8 個貼 ICP 的興趣;INTEREST_JSON 可整包覆蓋。
    格式 [["標籤", ["興趣id", ...]], ...] 或 [{"label":..,"ids":[..]}]。"""
    raw = os.environ.get("INTEREST_JSON")
    if raw:
        try:
            data = json.loads(raw)
            out = []
            for x in data:
                if isinstance(x, dict):
                    out.append((x["label"], [str(i) for i in x["ids"]]))
                else:
                    out.append((x[0], [str(i) for i in x[1]]))
            if out:
                return out
        except Exception as e:
            print(f"  (INTEREST_JSON 解析失敗,用內建清單: {e})")
    return W.INTERESTS


def run(round_tag):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    interests = _interests()
    cname = f"{N.campaign_name('Video')} · 興趣測試 · {round_tag}"

    print(f"[興趣測試] pixel={W.PIXEL} event={W.EVENT} · 每組 {W.BUDGET:.0f}/日 "
          f"· seed_winners={SEED_WINNERS} · DRY_RUN={C.DRY_RUN}")
    print(f"  campaign: {cname}（ABO / {C.OBJECTIVE} / PAUSED）")
    for lbl, ids in interests:
        print(f"    · 興趣 · {lbl}（{','.join(ids)}）")

    wins = W.winner_creatives(account) if SEED_WINNERS else []
    if SEED_WINNERS:
        print(f"  種子贏家素材: {[(k, c) for k, c in wins]}")

    if C.DRY_RUN:
        print("  （DRY:只排組,未建。設 DRY_RUN=false 才真的建,仍 PAUSED。）")
        return

    L.ensure_page_advertiser()
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}")

    n_aset, n_ad = 0, 0
    for gi, (lbl, ids) in enumerate(interests, 1):
        try:
            aset = W.make_interest_adset(account, camp, f"興趣 · {lbl}", ids)
        except Exception as e:
            print(f"  ⚠️ ad set「{lbl}」建立失敗: {str(e).replace(chr(10),' ')[:120]}")
            continue
        n_aset += 1
        print(f"  ── {lbl} ad set {aset}（興趣 {','.join(ids)}）")
        for kw, cid in wins:                       # SEED_WINNERS=false 時 wins 為空 → 留空 ad set
            nm = N.ad_name("SEED", gi * 10, re.sub(r"\s+", "", kw))
            try:
                ad = C.fb_retry(account.create_ad, params={
                    "name": nm, "adset_id": aset,
                    "creative": {"creative_id": cid}, "status": "PAUSED"})
                n_ad += 1
                print(f"     ✓ 種子 {kw} ad={ad['id']}")
            except Exception as e:
                print(f"     ⚠️ 種子 {kw} 失敗: {str(e).replace(chr(10),' ')[:100]}")
            time.sleep(W.PACE)
        time.sleep(W.PACE)
    print(f"→ 已建 {n_aset} 個興趣 ad set · {n_ad} 支種子廣告（全 PAUSED）。"
          f"之後把新測試廣告直接塞進這些 ad set。")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--round", default="T1", help="本輪標記,如 T1")
    args = p.parse_args()
    run(args.round)
