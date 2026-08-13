"""
影片 creative 自動產線:
  Drive 資料夾的新影片 → AI 依痛點+檔名鉤子寫長文案 → 上傳 Meta → 建影片廣告(PAUSED)

- 只處理沒上過的影片(用廣告名裡的 [gd:<fileId>] 去重)
- 合規容器沿用 launch 的做法(複製贏家母 campaign + clone 合規 ad set)
- AI 看不了整支影片,文案用「檔名鉤子 + WK 給的痛點 + 已驗證長文案框架」生成

env: GOOGLE_SA_JSON, ANTHROPIC_API_KEY, META_ACCESS_TOKEN, PAGE_ID, LANDING_URL
用法: python video_pipeline.py --round VID1
"""
import os, re, json, time, argparse, tempfile
import config as C
import launch as L
import kb as KB
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.advideo import AdVideo
from facebook_business.adobjects.adset import AdSet

# ⚠️ 指到「直接放 mp4 的資料夾」(素材待上架夾)。用 Secret DRIVE_FOLDER_ID 設。
# 注意:list 是非遞迴的,資料夾裡要直接是 mp4,不能是壓縮包或再一層子資料夾。
FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID") or "1dUaps14XcVFNJaz1KGVb8LiyYEFBfxQH"
COPY_MODEL = os.environ.get("COPY_MODEL") or "claude-sonnet-5"
FORCE = (os.environ.get("FORCE_REBUILD") or "").strip().lower() == "true"


def _load_style():
    """英文文案系統提示。單一真相 = prompts/caption_system.md(直接改文案不用動代碼)。"""
    p = C.ROOT / "prompts" / "caption_system.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ('Write a punchy English Facebook ad primary_text for a FREE AI Employee '
            'Blueprint Masterclass. Video theme: 《__FNAME__》. End with 4-6 hashtags. '
            'Reply JSON only: {"primary_text":"...","headline":"..."}')



def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def list_videos(svc):
    q = f"'{FOLDER_ID}' in parents and mimeType contains 'video/' and trashed=false"
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, fields="nextPageToken, files(id,name)",
                             pageToken=tok, pageSize=100).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


def download(svc, fid, path):
    from googleapiclient.http import MediaIoBaseDownload
    req = svc.files().get_media(fileId=fid)
    with open(path, "wb") as f:
        dl = MediaIoBaseDownload(f, req, chunksize=20 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def write_copy(fname):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=COPY_MODEL, max_tokens=3000,
        messages=[{"role": "user", "content": _load_style().replace("__FNAME__", fname)}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", txt, re.S)
    data = json.loads(m.group(0) if m else txt)
    return data["primary_text"].strip(), data["headline"].strip()


def upload_video(account, path):
    # 用 SDK 的分塊上傳(resumable),大檔才不會 413。
    v = AdVideo(parent_id=C.ACT_ID)
    v[AdVideo.Field.filepath] = path
    v.remote_create()
    return v[AdVideo.Field.id]


def wait_ready(video_id, tries=90, gap=10):
    for _ in range(tries):
        try:
            st = AdVideo(video_id).api_get(fields=["status"]).get("status", {})
            if st.get("video_status") == "ready":
                return True
        except Exception:
            pass
        time.sleep(gap)
    return False


def thumbnail(video_id):
    try:
        thumbs = list(AdVideo(video_id).get_thumbnails(fields=["uri", "is_preferred"]))
    except Exception:
        thumbs = []
    if not thumbs:
        return None
    pref = next((t["uri"] for t in thumbs if t.get("is_preferred")), None)
    return pref or thumbs[0].get("uri")


def create_video_ad(account, adset_id, video_id, thumb, pt, hl, name):
    vd = {"video_id": video_id, "message": pt, "title": hl,
          "call_to_action": {"type": "SIGN_UP", "value": {"link": C.LANDING_URL}}}
    if thumb:
        vd["image_url"] = thumb
    story = {"page_id": C.PAGE_ID, "video_data": vd}
    if C.INSTAGRAM_ID:
        story["instagram_actor_id"] = C.INSTAGRAM_ID
    cp = {"name": name, "object_story_spec": story}
    if C.URL_TAGS:
        cp["url_tags"] = C.URL_TAGS
    creative_id = account.create_ad_creative(params=cp)["id"]
    return account.create_ad(params={"name": name, "adset_id": adset_id,
                                     "creative": {"creative_id": creative_id},
                                     "status": "PAUSED"})["id"]


def already_uploaded_ids(account):
    ids = set()
    for ad in account.get_ads(fields=["name"], params={"limit": 1000}):
        m = re.search(r"\[gd:([A-Za-z0-9_-]+)\]", ad.get("name", ""))
        if m:
            ids.add(m.group(1))
    return ids


def run(round_tag):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    svc = drive_service()
    vids = list_videos(svc)
    kbo = KB.load()
    done = KB.done_ids(kbo) | already_uploaded_ids(account)
    new = vids if FORCE else [f for f in vids if f["id"] not in done]
    nums = KB.number_batch(new)          # V5→5 等檔名編號,沒有就自動 1..N
    print(f"[video] 資料夾共 {len(vids)} 支,已上 {len(vids)-len(new)},新影片 {len(new)} | DRY_RUN={C.DRY_RUN}")
    if not new:
        print("  沒有新影片,結束。")
        return

    adset_id = None
    if not C.DRY_RUN:
        L.ensure_page_advertiser()
        camp_name = N.campaign_name("Video")
        if C.WINNER_AD_KEYWORDS:
            # clone 模式:複製現成贏家 ad set 繼承合規(舊帳號有贏家時用)
            winners = L.find_winner_ads(account, C.WINNER_AD_KEYWORDS)
            if not winners:
                raise SystemExit("clone 模式找不到贏家 ad set;全新帳號請清空 WINNER_AD_KEYWORDS 走從零建。")
            src = winners[0]["adset_id"]
            camp = L.copy_source_campaign(account, camp_name, src)
            adset_id = L.clone_compliant_adset(account, camp, "tmp", src)
            tgt = AdSet(adset_id).api_get(fields=["targeting"]).get("targeting") or {}
            AdSet(adset_id).api_update(params={"name": N.adset_name(tgt)})
        else:
            # 從零建(全新市場,無現成贏家):CBO campaign + 合規 ad set(含 SG 法規欄位)
            camp = L.create_campaign(account, camp_name, with_budget=True)
            adset_id = L.create_ad_set(
                account, camp,
                N.adset_name({"age_min": C.AGE_MIN, "age_max": C.AGE_MAX}),
                {"key": "BROAD", "detailed_targeting": []})
        print(f"  容器建好: {camp_name} → ad set {adset_id}")

    n = 0
    for f in new:
        fid, fname = f["id"], f["name"]
        try:
            pt, hl = write_copy(fname)
        except Exception as e:
            print(f"  ⚠️ {fname} 寫文案失敗,跳過: {e}")
            continue
        print(f"  ── {fname}\n     標題: {hl}\n     文案({len(pt)}字): {pt[:50]}...")
        if C.DRY_RUN:
            continue
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, re.sub(r"[^\w.-]", "_", fname))
            try:
                download(svc, fid, p)
                vid = upload_video(account, p)
                print(f"     ↑ 上傳完成 video={vid},等待處理…")
                if not wait_ready(vid):
                    print("     ⚠️ 影片處理逾時,先跳過(稍後可重跑)")
                    continue
                theme = re.sub(r"\s+", "", hl)[:24] or fname[:16]
                name = N.ad_name("VID", nums[fid], theme)
                ad_id = create_video_ad(account, adset_id, vid, thumbnail(vid), pt, hl, name)
                KB.record(kbo, fid, "VID", nums[fid], ad_id, name, fname)
                n += 1
                print(f"     ✓ 建好影片廣告 ad={ad_id}")
            except Exception as e:
                print(f"     ⚠️ 建影片廣告失敗,跳過: {e}")
    if not C.DRY_RUN:
        KB.save(kbo)
        print(f"→ 已上 {n} 支新影片為 PAUSED 影片廣告。檢查無誤後開 ACTIVE。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="VID1")
    run(ap.parse_args().round)
