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
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.advideo import AdVideo

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID") or "1mUL6VRHG33kcPSL372ELSrZBB_R7ogN6"
COPY_MODEL = os.environ.get("COPY_MODEL") or "claude-sonnet-5"

STYLE = """你是 MTC「AI 自動回覆・幫你獲客」品牌的頂尖直效文案(Direct-Response)。
受眾:台灣中小企業老闆——有自己的官方生意(官網/粉專/IG/LINE),但有一個共同痛點:
**客人傳訊息進來,沒人回;或老闆丟給員工,員工兩天後才回——到那時客人早就沒有想買的感覺了。**
產品:一套「AI 收單系統/AI 員工」,24 小時自動回覆、聽得懂語音與台語粵語、處理價格疑慮與「我再想想」、
自動跟進、排預約、把冷掉的名單重新激活,一步步把對話推進到預約或結帳成交——不是死板的回覆機器人,是會「做銷售」的 AI。
Offer:一場「免費線上直播課」,現場打開後台拆解 AI 員工怎麼運作、怎麼複製到自己生意。CTA:點下方連結免費報名。

★這是我們『已驗證會賺錢』的長文案骨架,照這個長度(約 30~60 行)、結構、語氣、emoji 密度來寫:
痛點鉤子(緊扣這支影片的主題)→ 放大代價(例:一天漏 2 個詢問、客單一萬,一年白燒 72 萬 💸)→
揭露機制「來,看好 👀」→「這不是回覆機器人,是會做銷售的 AI 💰」→ 社會證明/急迫 →
免費直播課 🎙️ → 📍三個 bullet(客人說太貴 AI 自動處理 / 語音台語粵語都懂 / 24 小時回覆+跟進+預約+成交)→
名額有限 🔒 → 👇 點下方連結免費報名。用短句、大量斷行、用「.」當空行分隔,繁體中文。

這支影片的檔名(鉤子靈感):《{fname}》
請以這個檔名主題當開頭 3~5 行的鉤子,扣住「沒人回訊息 / 回太慢 = 流失客人」的痛點,其餘沿用骨架。
headline:<=20 字,一句話,呼應這支影片。
只回 JSON,格式: {{"primary_text": "...", "headline": "..."}} 不要其他字。"""


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
        model=COPY_MODEL, max_tokens=2500,
        messages=[{"role": "user", "content": STYLE.format(fname=fname)}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", txt, re.S)
    data = json.loads(m.group(0) if m else txt)
    return data["primary_text"].strip(), data["headline"].strip()


def upload_video(account, path):
    vid = account.create_ad_video(params={"source": path})
    return vid["id"]


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
    done = already_uploaded_ids(account)
    new = [f for f in vids if f["id"] not in done]
    print(f"[video] 資料夾共 {len(vids)} 支,已上 {len(vids)-len(new)},新影片 {len(new)} | DRY_RUN={C.DRY_RUN}")
    if not new:
        print("  沒有新影片,結束。")
        return

    base = f"{C.load_yaml('launch_template.yaml')['brand']['code']} | VID | {round_tag}"
    adset_id = None
    if not C.DRY_RUN:
        L.ensure_page_advertiser()
        winners = L.find_winner_ads(account, C.WINNER_AD_KEYWORDS)
        if not winners:
            raise SystemExit("找不到合規來源(贏家 ad set),無法建容器。")
        src = winners[0]["adset_id"]
        L.delete_existing_campaigns(account, base)
        camp = L.copy_source_campaign(account, base, src)
        adset_id = L.clone_compliant_adset(account, camp, base, src)
        print(f"  合規容器建好: campaign→ ad set {adset_id}")

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
                name = f"AI獲客 | VID | {theme} [gd:{fid}]"
                ad_id = create_video_ad(account, adset_id, vid, thumbnail(vid), pt, hl, name)
                n += 1
                print(f"     ✓ 建好影片廣告 ad={ad_id}")
            except Exception as e:
                print(f"     ⚠️ 建影片廣告失敗,跳過: {e}")
    if not C.DRY_RUN:
        print(f"→ 已上 {n} 支新影片為 PAUSED 影片廣告。檢查無誤後開 ACTIVE。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="VID1")
    run(ap.parse_args().round)
