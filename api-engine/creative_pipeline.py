"""
圖片 creative 自動產線:
  Drive 資料夾放新圖 → 抓新圖 → Anthropic 看圖寫專屬文案 → 上傳 Meta → 建圖片廣告(PAUSED)

- 只處理「沒上過」的圖(用廣告名裡的 [gd:<fileId>] 標記去重)
- 合規容器沿用 launch 的做法(複製贏家母 campaign + clone 合規 ad set，繼承台灣廣告主聲明)
- DRY_RUN=true 時只列新圖 + 印文案，不真的建

需要的 env / Secret:
  GOOGLE_SA_JSON, ANTHROPIC_API_KEY, META_ACCESS_TOKEN(+ config 其餘預設)
用法: python creative_pipeline.py --round IMG1
"""
import os, re, json, base64, argparse, tempfile, io
import config as C
import launch as L
from facebook_business.adobjects.adaccount import AdAccount

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "1mUL6VRHG33kcPSL372ELSrZBB_R7ogN6")
COPY_MODEL = os.environ.get("COPY_MODEL", "claude-sonnet-5")

STYLE = """你是 MTC「AI 自動回覆・幫你獲客」品牌的廣告文案。受眾:台灣中小企業老闆、店家。
產品:一個 AI 員工,能 24 小時自動回覆客戶訊息(LINE/IG/FB)、自動跟進、把詢問推進到成交。
Offer/CTA:報名「免費線上分享會」現場示範。語氣:又直又痛、口語、繁體中文。

風格參考(照這個調):
- 「老闆,你下班了,客人的訊息誰在回?AI 員工 24 小時自動回覆…👉 免費線上分享會,現場示範:」/ 標題「你休息,AI 幫你接單」
- 「半夜、假日還在回 LINE?老闆不該當 24 小時免費客服…👉 免費分享會:」/ 標題「別再當 24 小時免費客服」
- 「對手已經用 AI 秒回接單,你還在手動打字、漏回訊息?…👉 免費分享會:」/ 標題「對手用 AI 秒回,你呢?」

看這張廣告圖,寫一則『貼文文案 primary_text』+ 一個『標題 headline』,要跟圖上的主視覺/鉤子呼應。
primary_text:3~4 短行,最後一行用「👉」帶到免費分享會 CTA。headline:<=18 字,一句話。
只回 JSON,格式: {"primary_text": "...", "headline": "..."} 不要其他字。"""


def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def list_images(svc):
    q = (f"'{FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false")
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, fields="nextPageToken, files(id,name,mimeType)",
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
        dl = MediaIoBaseDownload(f, req)
        done = False
        while not done:
            _, done = dl.next_chunk()


def write_copy(img_path, media_type):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    b64 = base64.standard_b64encode(open(img_path, "rb").read()).decode()
    msg = client.messages.create(
        model=COPY_MODEL, max_tokens=600,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": STYLE},
        ]}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", txt, re.S)
    data = json.loads(m.group(0) if m else txt)
    return data["primary_text"].strip(), data["headline"].strip()


def upload_image(account, path):
    img = account.create_ad_image(params={"filename": path})
    if img.get("hash"):
        return img["hash"]
    imgs = img.get("images") or {}
    return next(iter(imgs.values()))["hash"]


def create_image_ad(account, adset_id, image_hash, primary_text, headline, name):
    story = {"page_id": C.PAGE_ID, "link_data": {
        "image_hash": image_hash, "link": C.LANDING_URL,
        "message": primary_text, "name": headline,
        "call_to_action": {"type": "SIGN_UP", "value": {"link": C.LANDING_URL}}}}
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
    imgs = list_images(svc)
    done = already_uploaded_ids(account)
    new = [f for f in imgs if f["id"] not in done]
    print(f"[creative] 資料夾共 {len(imgs)} 張，已上 {len(imgs)-len(new)}，新圖 {len(new)} | DRY_RUN={C.DRY_RUN}")
    if not new:
        print("  沒有新圖，結束。")
        return

    base = f"{C.load_yaml('launch_template.yaml')['brand']['code']} | IMG | {round_tag}"
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
        mt = "image/jpeg" if fname.lower().endswith((".jpg", ".jpeg")) else "image/png"
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, fname)
            try:
                download(svc, fid, p)
                pt, hl = write_copy(p, mt)
            except Exception as e:
                print(f"  ⚠️ {fname} 下載/寫文案失敗,跳過: {e}")
                continue
            print(f"  ── {fname}\n     標題: {hl}\n     文案: {pt[:60]}...")
            if C.DRY_RUN:
                continue
            name = f"{base} | {fname[:20]} [gd:{fid}]"
            try:
                ad_id = create_image_ad(account, adset_id, upload_image(account, p), pt, hl, name)
                n += 1
                print(f"     ✓ 建好圖片廣告 ad={ad_id}")
            except Exception as e:
                print(f"     ⚠️ 建廣告失敗,跳過: {e}")
    if not C.DRY_RUN:
        print(f"→ 已上 {n} 張新圖為 PAUSED 圖片廣告。檢查無誤後開 ACTIVE。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="IMG1")
    run(ap.parse_args().round)
