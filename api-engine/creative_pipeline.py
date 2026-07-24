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

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID") or "1mUL6VRHG33kcPSL372ELSrZBB_R7ogN6"
COPY_MODEL = os.environ.get("COPY_MODEL") or "claude-sonnet-5"

STYLE = """你是 MTC「AI 自動回覆・幫你獲客」品牌的頂尖直效文案(Direct-Response)。
受眾:台灣中小企業老闆——美業、健身、診所、房產、顧問、課程導師、實體店家,靠私訊(LINE/IG/FB)成交。
產品:一套「AI 收單系統/AI 員工」,24 小時自動回覆、聽得懂語音與台語粵語、處理價格疑慮與「我再想想」、
自動跟進、排預約、把冷掉的名單重新激活、一步步把對話推進到預約或結帳成交——不是死板的回覆機器人,是會「做銷售」的 AI。
Offer:一場「免費線上直播課」,現場打開後台拆解 AI 員工怎麼運作、怎麼複製到自己生意。CTA:點下方連結免費報名。

★這是我們『已驗證會賺錢』的長文案範本,請照這個長度、結構、語氣、emoji 密度來寫(不要縮短成三行):

---範本(約 60~70 行)---
你不是在自動化,
你是在把客人親手送給你的對手 🙅
.
客人問一句「價格多少」,
機器人丟一張死板的價目表,
然後呢?客人就消失了。
.
高客單的客人,需要的是「被引導、被解除疑慮」🧠
你只丟一個冷冰冰的價格,他當然只會去跟別人比價!
.
你每天忙到沒時間回訊息,一天漏掉 2 個詢問,客單一萬,
一年就白白燒掉 72 萬 💸
最可怕的是——你根本不知道自己在燒錢,
因為那些客人是「安靜地離開」的 😶
.
所以別再用「聊天工具」了,你需要的是一套「AI 收單系統」⚙️
來,看好 👀
客人傳語音,它聽得懂 🗣️ 客人用台語嫌太貴,它不會當機!
它會像你最頂尖的超級業務,自動處理猶豫、處理「我再想想」,
一步步把對話推進到客人點擊預約、直接結帳收單 ⚡
這不是回覆機器人,這是會「做銷售」的 AI 💰
.
它不睡覺、沒情緒、不會忘記跟進,把你 LINE 裡問一半就冷掉的「沉默資產」全部重新激活。
當你員工下班,你的對手正用這套系統 24 小時把你的潛在客戶搶過去 🌙
.
如果你是靠私訊成交的老闆——美業、健身、顧問、課程導師,這套就是為你打造的 🎯
我準備了一場免費線上直播課 🎙️ 直接打開後台,拆解這套 AI 員工怎麼運作、你如何複製到你的生意。
📍 客人說太貴——AI 自動處理價格疑慮
📍 語音、台語、粵語——全部聽得懂
📍 24 小時自動回覆 + 跟進 + 預約 + 成交
名額有限,先到先得 🔒
👇 點擊下方連結,立即免費報名
把基礎事務交給 AI 員工,你去專注搞更重要的東西 🏃
---範本結束---

任務:看這張廣告圖,寫一則專屬的長文案 primary_text + 一個標題 headline。
- primary_text:照範本的長度(約 40~70 行)、結構(痛點鉤子→放大代價→揭露機制「來看好」→這不是機器人是會銷售的AI→社會證明/急迫→免費直播課→📍三個 bullet→👇報名CTA)、語氣與 emoji 密度。
- 【關鍵】開頭 3~5 行的鉤子,必須緊扣『這張圖上的主視覺/文字/情境』,不要每張都一樣。中後段可沿用範本骨架。
- 用短句、大量斷行、用「.」當空行分隔,讓版面透氣。繁體中文。
- headline:<=20 字,一句話,呼應這張圖的鉤子。
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
        model=COPY_MODEL, max_tokens=2500,
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
            if C.DRY_RUN:
                print(f"\n===== {fname} =====\n[標題] {hl}\n[文案] ({len(pt)} 字 / {len(pt.splitlines())} 行)\n{pt}\n")
                continue
            print(f"  ── {fname}\n     標題: {hl}\n     文案: {pt[:60]}...")
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
