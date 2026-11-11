"""
在「地區測試」campaign 的『雙北桃園』ad set 裡,加多 3 支「不重複」的影片廣告。

目的:用更多 proven creative 分散疲勞、壓低 CPL。
作法:
- 找到 campaign(名稱含 地區測試 + T1)→ 找到 ad set(名稱含 雙北桃園)。
- 讀該 ad set 現有廣告的 video_id,當成「排除清單」(避免重複;含贏家 M1Video9 1457047252416770)。
- 掃帳號現有廣告,依優先關鍵字(M1Video1 幾點下班 / M1Video11 用過LINE / M1Video4 30天挑戰…)
  找 proven 影片的 creative_id,解析其 video_id,去重後選 3 支。
- 直接引用既有 creative_id 在該 ad set 建廣告(不重做素材、不重傳影片),全 PAUSED。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, ADD_N(預設3), DRY_RUN(預設 true)
用法: DRY_RUN=false python add_geo_videos.py
"""
import os, time
import config as C
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adcreative import AdCreative

ADD_N = int(os.environ.get("ADD_N") or 3)
PACE = float(os.environ.get("PACE_SEC") or 3)
CAMP_MUST = [s for s in (os.environ.get("CAMP_MUST") or "地區測試,T1").split(",") if s]
ADSET_MUST = os.environ.get("ADSET_MUST") or "雙北桃園"
SEED_EXCLUDE = {"1457047252416770"}  # M1Video9 贏家,已在 ad set 裡

# 想加的 proven 影片:每個 slot 依序試這些名稱關鍵字,挑到就用
TARGETS = [
    ("M1Video1·幾點下班", ["幾點下班", "下班了沒", "幾點下班了"]),
    ("M1Video11·用過LINE", ["你有用過", "用過 LINE", "有用過 LINE", "用過LINE"]),
    ("M1Video4·30天挑戰", ["30天", "30 天", "三十天", "天挑戰"]),
]


def _cid(cr):
    if not cr:
        return None
    try:
        return cr["id"]
    except Exception:
        return cr.get("id") if hasattr(cr, "get") else None


def creative_video_id(cid):
    if not cid:
        return None
    try:
        cr = C.fb_retry(lambda: AdCreative(cid).api_get(fields=["video_id", "object_story_spec"]))
        if cr.get("video_id"):
            return str(cr["video_id"])
        oss = cr.get("object_story_spec") or {}
        vd = oss.get("video_data") or {}
        if vd.get("video_id"):
            return str(vd["video_id"])
    except Exception:
        pass
    return None


def find_campaign(account):
    camps = C.fb_retry(lambda: list(account.get_campaigns(fields=["name"], params={"limit": 500})))
    hits = [c for c in camps if all(m in (c.get("name") or "") for m in CAMP_MUST)]
    return hits[0] if hits else None


def find_adset(camp_id):
    sets_ = C.fb_retry(lambda: list(Campaign(camp_id).get_ad_sets(fields=["name"], params={"limit": 200})))
    for s in sets_:
        if ADSET_MUST in (s.get("name") or ""):
            return s
    return None


def existing_video_ids(adset_id):
    out = set()
    ads = C.fb_retry(lambda: list(AdSet(adset_id).get_ads(fields=["name", "creative"], params={"limit": 200})))
    for a in ads:
        vid = creative_video_id(_cid(a.get("creative")))
        if vid:
            out.add(vid)
    return out, [a.get("name") for a in ads]


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)

    camp = find_campaign(account)
    if not camp:
        raise SystemExit(f"找不到 campaign(需含 {CAMP_MUST})。")
    aset = find_adset(camp["id"])
    if not aset:
        raise SystemExit(f"在 campaign {camp['id']} 找不到 ad set(需含『{ADSET_MUST}』)。")
    print(f"[加影片] campaign {camp['id']}：{camp.get('name')}")
    print(f"         ad set  {aset['id']}：{aset.get('name')}")

    have, have_names = existing_video_ids(aset["id"])
    exclude = set(SEED_EXCLUDE) | have
    print(f"  現有廣告 {len(have_names)} 支,已用 video_id={sorted(have)}；排除={sorted(exclude)}")

    # 掃帳號所有廣告,建 (name, creative_id) 清單
    allads = C.fb_retry(lambda: list(account.get_ads(fields=["name", "creative"], params={"limit": 2000})))
    allads = [((a.get("name") or ""), _cid(a.get("creative"))) for a in allads]
    print(f"  掃到帳號 {len(allads)} 支現有廣告,開始配對…")

    chosen = []  # (label, name, creative_id, video_id)
    picked_vids = set()

    def try_pick(label, kw_list):
        for kw in kw_list:
            for nm, cid in allads:
                if kw in nm and cid:
                    vid = creative_video_id(cid)
                    if vid and vid not in exclude and vid not in picked_vids:
                        chosen.append((label, nm, cid, vid))
                        picked_vids.add(vid)
                        return True
        return False

    for label, kws in TARGETS:
        if len(chosen) >= ADD_N:
            break
        ok = try_pick(label, kws)
        print(f"  · {label}: {'✓ '+chosen[-1][1][:44]+f'  (video {chosen[-1][3]})' if ok else '✗ 沒配到(或 video 重複)'}")

    # 補位:若不足 ADD_N,從帳號其他「不重複」影片補(取出現最多的 distinct video)
    if len(chosen) < ADD_N:
        from collections import Counter
        freq = Counter()
        samp = {}
        for nm, cid in allads:
            vid = creative_video_id(cid) if cid else None
            if vid and vid not in exclude and vid not in picked_vids:
                freq[vid] += 1
                samp.setdefault(vid, (nm, cid))
        for vid, _ in freq.most_common():
            if len(chosen) >= ADD_N:
                break
            nm, cid = samp[vid]
            chosen.append(("補位·其他影片", nm, cid, vid))
            picked_vids.add(vid)
            print(f"  · 補位: ✓ {nm[:44]}  (video {vid})")

    print(f"→ 準備加 {len(chosen)}/{ADD_N} 支(全不重複)到『{aset.get('name')}』| DRY_RUN={C.DRY_RUN}")
    for lbl, nm, cid, vid in chosen:
        print(f"     [{lbl}] creative={cid} video={vid}  ← {nm[:50]}")
    if not chosen:
        raise SystemExit("沒有可加的非重複影片,停手。")
    if C.DRY_RUN:
        print("  (DRY:只配對,未建。DRY_RUN=false 才真的建。)")
        return

    n = 0
    for i, (lbl, nm, cid, vid) in enumerate(chosen, 1):
        adname = N.ad_name("VID", i, f"雙北桃園+{lbl}")
        try:
            ad = C.fb_retry(account.create_ad, params={
                "name": adname, "adset_id": aset["id"],
                "creative": {"creative_id": cid}, "status": "PAUSED"})
            n += 1
            print(f"     ✓ 引用 {cid}(video {vid}) → ad {ad['id']}  {adname}")
        except Exception as e:
            print(f"     ⚠️ 失敗: {str(e).replace(chr(10),' ')[:140]}")
        time.sleep(PACE)
    print(f"→ 已加 {n}/{len(chosen)} 支影片廣告到『{aset.get('name')}』(PAUSED)。")


if __name__ == "__main__":
    run()
