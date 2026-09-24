"""
把 Drive 資料夾的新影片上成 Meta 影片廣告,開一個新的 ABO campaign 專跑。

- 影片:DRIVE_FOLDER_ID(用 SA 讀),依固定角度順序排(V1..V8, V11, 自由發揮, Hook…)。
- 文案:每支『重新生成』長文案(沿用 video_pipeline 的 STYLE,claude 產)。
- 結構:ABO;每 ad set ≤ VIDEOS_PER_ADSET(2)支;每組 IMAGE_ADSET_BUDGET(500)TWD/日。
- 定向/合規:沿用 launch_static_ads.make_abo_adset(台灣·30-55·繁中 locale22·手動版位·clone 贏家合規)。
- ACTIVATE=true 且全部建成 → 開 ACTIVE。DRY_RUN=true 只印配對,不建、不產文案。

env: DRIVE_FOLDER_ID, GOOGLE_SA_JSON, ANTHROPIC_API_KEY, META_ACCESS_TOKEN, PAGE_ID, LANDING_URL,
     IMAGE_ADSET_BUDGET(=500), VIDEOS_PER_ADSET(=2), ACTIVATE …
"""
import os, re, time, tempfile
import config as C
import launch as L
import naming as N
import launch_static_ads as LS
import video_pipeline as VP
from facebook_business.adobjects.adaccount import AdAccount

PER_ADSET = int(os.environ.get("VIDEOS_PER_ADSET") or 2)
PACE = float(os.environ.get("PACE_SEC") or 3)


def order_rank(name):
    """依角度固定排序:V1..V8 → V11 → 自由發揮 → Hook1,5,6,7,8,9,11。"""
    m = re.match(r"\s*[Vv](\d+)", name)
    if m:
        v = int(m.group(1))
        seq = [1, 2, 3, 4, 5, 6, 7, 8, 11]
        return (0, seq.index(v) if v in seq else 90 + v)
    if "自由發揮" in name or "自由发挥" in name:
        return (0, 9.5)
    m = re.search(r"[Hh][Oo][Oo][Kk]\s*_?\s*(\d+)", name)
    if m:
        h = int(m.group(1))
        seq = [1, 5, 6, 7, 8, 9, 11]
        return (1, seq.index(h) if h in seq else 90 + h)
    return (2, 99)


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    svc = VP.drive_service()
    vids = VP.list_videos(svc)                      # 用 VP.FOLDER_ID = env DRIVE_FOLDER_ID
    vids.sort(key=lambda f: order_rank(f["name"]))
    groups = [vids[i:i + PER_ADSET] for i in range(0, len(vids), PER_ADSET)]
    print(f"[drive-video] 影片 {len(vids)} 支 → {len(groups)} 個 ad set(每組≤{PER_ADSET}) · "
          f"ABO {LS.ADSET_BUDGET:.0f} TWD/組/日 | DRY_RUN={C.DRY_RUN}")
    for gi, g in enumerate(groups, 1):
        print(f"  組{gi}: " + " ＋ ".join(f["name"] for f in g))
    if not vids:
        print("  資料夾沒有影片,結束。")
        return
    if C.DRY_RUN:
        print("  （DRY:只讀+排組,未產文案、未建廣告）")
        return

    L.ensure_page_advertiser()
    winners = C.fb_retry(L.find_winner_ads, account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到合規來源(贏家 ad set),無法建容器。")
    src = winners[0]["adset_id"]
    cname = N.campaign_name("Video")
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}（{LS.ADSET_BUDGET:.0f} TWD/組/日）")

    total = len(vids)
    n = 0
    idx = 0
    for gi, g in enumerate(groups, 1):
        adset_id = LS.make_abo_adset(account, camp, src, f"組{gi}")
        print(f"  ── 組{gi} ad set {adset_id}(台灣 · 30-55 · 繁中 · 手動版位）")
        for f in g:
            idx += 1
            fid, fname = f["id"], f["name"]
            try:
                pt, hl = VP.write_copy(fname)
            except Exception as e:
                print(f"     ⚠️ {fname} 產文案失敗,跳過: {e}")
                continue
            theme = re.sub(r"\s+", "", hl)[:24] or fname[:16]
            name = N.ad_name("VID", idx, theme)
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, re.sub(r"[^\w.-]", "_", fname))
                try:
                    VP.download(svc, fid, p)
                    vid = C.fb_retry(VP.upload_video, account, p)
                    print(f"     ↑ {fname}｜標題:{hl}｜文案{len(pt)}字｜video={vid} 等待處理…")
                    if not VP.wait_ready(vid):
                        print("       ⚠️ 影片處理逾時,先跳過(稍後可重跑)")
                        continue
                    ad_id = C.fb_retry(VP.create_video_ad, account, adset_id, vid,
                                       VP.thumbnail(vid), pt, hl, name)
                    n += 1
                    print(f"       ✓ 廣告 ad={ad_id}")
                except Exception as e:
                    print(f"       ⚠️ 建影片廣告失敗,跳過: {e}")
            time.sleep(PACE)
        time.sleep(PACE * 3)
    print(f"→ 已上 {n}/{total} 支影片於 ABO campaign(PAUSED)。")
    if LS.ACTIVATE and n == total:
        LS.activate_all(camp)
    elif LS.ACTIVATE:
        print(f"  ⚠️ 只建了 {n}/{total},先不自動開 ACTIVE,留 PAUSED(可重跑補齊)。")


if __name__ == "__main__":
    run()
