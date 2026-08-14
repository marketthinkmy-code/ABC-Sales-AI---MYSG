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
from facebook_business.adobjects.campaign import Campaign

FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID") or "1mUL6VRHG33kcPSL372ELSrZBB_R7ogN6"
COPY_MODEL = os.environ.get("COPY_MODEL") or "claude-sonnet-5"
FORCE = (os.environ.get("FORCE_REBUILD") or "").strip().lower() == "true"
# 影片 campaign 用 CBO,預算在 campaign 層(WK 指定 2000 TWD/日)。
VIDEO_BUDGET = float(os.environ.get("VIDEO_CBO_BUDGET") or 2000)
# 一個 ad set 最多放幾支影片(WK 指定 3)。16 支 → 6 個 ad set(3/3/3/3/2/2)。
PER_ADSET = int(os.environ.get("VIDEOS_PER_ADSET") or 3)
# 每支/每組之間的節流秒數,避免爆量觸發帳號速率限制。
PACE = float(os.environ.get("PACE_SEC") or 3)
# APPEND=true:不刪 campaign,只把「KB 裡還沒記錄」的影片補上(補跑失敗的那幾支用)。
APPEND = (os.environ.get("APPEND") or "").strip().lower() == "true"

STYLE = """你是 MTC「AI 自動回覆・幫你獲客」品牌的頂尖直效文案(Direct-Response)。全部用繁體中文。
受眾:台灣靠私訊成交的老闆(美業、健身、顧問、課程導師、實體店)——有自己的官方生意(官網/粉專/IG/LINE),
共同痛點:客人傳訊息進來沒人回;或老闆丟給員工,員工隔天甚至兩天後才回——到那時客人早就沒有想買的感覺,跑去對手那邊了。
產品:一套「以成交為主的 AI 員工 / AI 收單系統」,不是 Manychat/關鍵字機器人那種一問複雜就當機、傳語音沒反應的東西;
它 1 秒人性化回覆、聽得懂語音與台語粵語、處理「我再想想」的猶豫、已讀不回自動在對的時間跟進、自動排預約、把冷掉的沉默名單重新激活,一路推進到預約或結帳成交。
Offer:一場「免費線上直播課/分享會」,現場打開後台示範 AI 員工怎麼運作、怎麼複製到自己生意。CTA:點下方連結免費報名。

===== 這是我們『已驗證會賺錢』的長文案範例,你要『模仿這種』的長度、語氣、節奏、結構、emoji 密度(每則約 600~1000 字、大量短句斷行、用空行分隔) =====

【範例A・幾點下班】
你的員工都下班了,但你的 LINE 還有客人在問——是誰在回?🤔
很多老闆覺得,員工下班了今天生意就結束了。客人晚上問的,明天再回就好?
但真實情況是:你的員工回家了,你的客人沒有 🌙 他晚上 10 點傳 LINE 問預約、問價格,你隔天早上才回,他已經在別家訂好了。
你以為只是晚回幾小時,但對客人來說,他等到的是「你不在乎」。而你每天漏掉的不只是訊息,是一筆一筆本來能成交的錢 💸
更慘的是——你甚至不知道自己在漏單,只看到這個月業績又不穩定。
所以我請了一個「不用回家」的員工 🤖 它不是 Manychat 或關鍵字機器人那種一問複雜就當機的東西 🙅,它是「以成交為主」的 AI:
客人說「我再考慮看看」它知道怎麼接 ⚡ 客人已讀不回它知道何時跟進、說什麼;客人傳照片問狀況,它不只回覆還直接把預約約好 📅
它把本來要流掉的名單一個一個抓回來 💰。它不是取代你的員工,而是 AI 接住每個詢問、員工服務準備好的客人,兩個加在一起最好。
語音也能處理,連台語都聽得懂 🗣️ LINE、IG、Messenger 全部串接,24 小時不休息。
所以我準備了一場免費線上分享會 🎙️ 現場示範它怎麼自動回覆、自動跟進、自動推進成交,讓你睡覺時還在幫你收單!
📍 不需要懂任何程式碼
📍 AI 自動回覆 + 跟進 + 預約 + 成交
📍 語音、台語都聽得懂,人性化回覆
名額有限,先到先得 🔒
👇 點擊下方連結,立即免費報名
你的員工可以下班,但你的業績不能下班 🏃

【範例B・如果你還在用】
你以為在用 AI,其實只是在趕走客人 😱 這句話很刺,但你聽完就知道為什麼。
如果你現在還在用 Chatbot、Manychat 或 LINE 關鍵字自動回覆,你不是在自動化,你是在把客人親手送給對手 🙅
客人問一句「價格多少」,機器人丟一張死板的價目表,然後呢?客人就消失了。
高客單的客人要的是「被引導、被解除疑慮」🧠 你只丟一個冷冰冰的價格,他當然只會去比價!
你每天忙到沒時間回訊息,一天漏 2 個詢問、客單一萬,一年就白燒 72 萬 💸 最可怕的是你根本不知道自己在燒錢,因為那些客人是「安靜地離開」的 😶
所以別再用「聊天工具」,你需要一套「AI 收單系統」⚙️ 來,看好 👀
客人傳語音它聽得懂 🗣️ 用台語嫌太貴它不會當機!它像你最頂尖的超級業務,自動處理猶豫、處理「我再想想」,一步步把對話推進到點擊預約或直接結帳收單 ⚡
這不是回覆機器人,這是會「做銷售」的 AI 💰 它不睡覺、沒情緒、不會忘記 follow up,把你 LINE 裡加了好友、問一半就冷掉的「沉默資產」全部重新激活。
當你員工下班,你的對手正用這套系統 24 小時把你的客戶搶過去 🌙
如果你是靠私訊成交、做美業/健身/顧問/課程導師的,這套就是為你打造的 🎯 我準備了一場免費線上直播課 🎙️ 直接打開後台拆解它怎麼運作、你如何複製到你的生意。
📍 客人說太貴——AI 自動處理價格疑慮
📍 語音、台語、粵語——全部聽得懂
📍 24 小時自動回覆 + 跟進 + 預約 + 成交
名額有限,先到先得 🔒
👇 點擊下方連結,立即免費報名
把基礎事務交給 AI 員工,你去專注搞更重要的東西 🏃
===== 範例結束 =====

任務:這支影片的檔名(鉤子主題)是《__FNAME__》。
請『模仿上面範例的那種』寫一則全新的長文案 primary_text:
- 長度、語氣、節奏、斷行、emoji 密度都要跟範例一樣(約 600~1000 字,不要縮短)。
- 開頭 3~5 行的鉤子要緊扣這支影片檔名的主題,並扣住「沒人回訊息 / 回太慢 = 流失客人」的痛點。
- 中後段沿用骨架:揭露 AI 員工(強調不是 Manychat/關鍵字機器人)→ 處理猶豫/已讀不回自動跟進/語音台語 → 不取代員工是配合 → 免費直播課 → 📍三個 bullet → 名額有限 🔒 → 👇 CTA → 一句金句收尾。
- 內容只講這個產品與痛點,不要寫無關的東西。全繁體中文。
headline:<=20 字,一句話,呼應這支影片。
只回 JSON,格式: {"primary_text": "...", "headline": "..."} 不要其他字。"""


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
        messages=[{"role": "user", "content": STYLE.replace("__FNAME__", fname)}])
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


def tw_chinese_locales():
    """回傳台灣繁體中文的 Meta locale key。動態查,查不到就用預設 [31]=Chinese(Taiwan)。"""
    try:
        from facebook_business.adobjects.targetingsearch import TargetingSearch
        rows = TargetingSearch.search(params={"q": "Chinese", "type": "adlocale"})
        keys = []
        for r in rows:
            nm = (r.get("name") or "")
            if "Taiwan" in nm or "Traditional" in nm:
                keys.append(int(r["key"]))
        if keys:
            return sorted(set(keys))
    except Exception as e:
        print(f"  (locale 查詢失敗,用預設繁中 Chinese(Taiwan): {e})")
    return [31]   # 31 = Chinese (Taiwan),繁體


def find_campaign(account, name):
    camps = C.fb_retry(lambda: list(account.get_campaigns(
        fields=["id", "name"], params={"limit": 200})))
    for c in camps:
        if (c.get("name") or "") == name:
            return c["id"]
    return None


def make_tw_adset(account, camp, src, locales, tmpl, group_idx):
    """clone 合規 ad set 到 CBO campaign,覆寫成 台灣 + 繁體中文 的廣泛受眾,依規則命名。"""
    adset_id = L.clone_compliant_adset(account, camp, "tmp", src)
    # 台灣地區 + 繁體中文語言(WK:Location=台灣、Language=繁中,絕對不變)。
    C.fb_retry(AdSet(adset_id).api_update, params={"targeting": {
        "geo_locations": {"countries": tmpl["geo"]["countries"]},   # ["TW"]
        "age_min": tmpl.get("age_min", 25),
        "age_max": tmpl.get("age_max", 55),
        "locales": locales,
    }})
    tgt = C.fb_retry(lambda: AdSet(adset_id).api_get(fields=["targeting"]).get("targeting")) or {}
    C.fb_retry(AdSet(adset_id).api_update, params={"name": f"{N.adset_name(tgt)} · 組{group_idx}"})
    return adset_id


def run(round_tag):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    svc = drive_service()
    vids = list_videos(svc)
    kbo = KB.load()
    # 兩種語意:
    #  預設(整批重建):刪同名 campaign + 重建資料夾裡全部影片,不做 KB 去重。
    #  APPEND:不刪 campaign,只補「KB 還沒記錄」的影片(補跑上次失敗那幾支)。
    if APPEND:
        done = KB.done_ids(kbo)
        new = [f for f in vids if f["id"] not in done]
    else:
        new = list(vids)
    nums = KB.number_batch(new)          # V5→5 等檔名編號,沒有就自動 1..N
    # 每 PER_ADSET 支切一個 ad set(WK:一個 asset 最多 3 支)。
    groups = [new[i:i + PER_ADSET] for i in range(0, len(new), PER_ADSET)]
    print(f"[video] 資料夾共 {len(vids)} 支,{'APPEND 補' if APPEND else '重建'} {len(new)} 支 "
          f"→ {len(groups)} 個 ad set(每組≤{PER_ADSET}) | DRY_RUN={C.DRY_RUN}")
    if not new:
        print("  沒有要處理的影片,結束。")
        return
    for gi, g in enumerate(groups, 1):
        print(f"  組{gi}: {[f['name'] for f in g]}")

    if C.DRY_RUN:
        for f in new:
            try:
                pt, hl = write_copy(f["name"])
                print(f"\n===== {f['name']} (#{nums[f['id']]}) =====\n[標題] {hl}\n[文案 {len(pt)}字]\n{pt}\n")
            except Exception as e:
                print(f"  ⚠️ {f['name']} 寫文案失敗: {e}")
        return

    L.ensure_page_advertiser()
    winners = C.fb_retry(L.find_winner_ads, account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到合規來源(贏家 ad set),無法建容器。")
    src = winners[0]["adset_id"]
    tmpl = C.load_yaml("launch_template.yaml")["ad_set"]
    locales = tw_chinese_locales()
    print(f"  繁體中文 locale = {locales}")
    cname = N.campaign_name("Video")
    gstart = 1
    if APPEND:
        camp = find_campaign(account, cname)
        if camp:
            existing = C.fb_retry(lambda: list(Campaign(camp).get_ad_sets(fields=["id"])))
            gstart = len(existing) + 1
            print(f"  APPEND:沿用現有 campaign {camp}(已有 {len(existing)} 個 ad set,補的從 組{gstart} 起)")
    else:
        camp = None
    if not camp:
        # 重跑先清掉同名的舊 PAUSED campaign,避免重複。
        if not APPEND:
            L.delete_existing_campaigns(account, cname)
        # CBO campaign(預算在 campaign 層 = WK 指定 2000 TWD/日),objective 沿用帳號設定。
        camp = C.fb_retry(account.create_campaign, params={
            "name": cname, "objective": C.OBJECTIVE,
            "special_ad_categories": [], "status": "PAUSED",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "daily_budget": C.to_minor(VIDEO_BUDGET),
        })["id"]
        print(f"  ✓ CBO campaign {camp}(日預算 {VIDEO_BUDGET:.0f} TWD): {cname}")

    n = 0
    for gi, g in enumerate(groups, gstart):
        adset_id = make_tw_adset(account, camp, src, locales, tmpl, gi)
        print(f"  ── 組{gi} ad set {adset_id}(台灣 · 繁中)")
        for f in g:
            fid, fname = f["id"], f["name"]
            try:
                pt, hl = write_copy(fname)
            except Exception as e:
                print(f"     ⚠️ {fname} 寫文案失敗,跳過: {e}")
                continue
            print(f"     · {fname}｜標題:{hl}｜文案{len(pt)}字")
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, re.sub(r"[^\w.-]", "_", fname))
                try:
                    download(svc, fid, p)
                    vid = C.fb_retry(upload_video, account, p)
                    print(f"       ↑ 上傳 video={vid},等待處理…")
                    if not wait_ready(vid):
                        print("       ⚠️ 影片處理逾時,先跳過(稍後可重跑)")
                        continue
                    theme = re.sub(r"\s+", "", hl)[:24] or fname[:16]
                    name = N.ad_name("VID", nums[fid], theme)
                    ad_id = C.fb_retry(create_video_ad, account, adset_id, vid,
                                       thumbnail(vid), pt, hl, name)
                    KB.record(kbo, fid, "VID", nums[fid], ad_id, name, fname)
                    if APPEND:
                        KB.save(kbo)     # 補跑模式即存,失敗重跑會跳過已補好的
                    n += 1
                    print(f"       ✓ 廣告 ad={ad_id}")
                except Exception as e:
                    print(f"       ⚠️ 建影片廣告失敗,跳過: {e}")
            time.sleep(PACE)              # 每支之間稍等,避免爆量觸發限流
        time.sleep(PACE * 3)             # 每個 ad set 之間多等一下
    KB.save(kbo)
    print(f"→ 已上 {n} 支影片,分 {len(groups)} 個 ad set(台灣·繁中,CBO {VIDEO_BUDGET:.0f}/日),全 PAUSED。檢查無誤後開 ACTIVE。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="VID1")
    run(ap.parse_args().round)
