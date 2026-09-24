"""
把 Drive 資料夾裡『已做好的靜圖廣告』上成 Meta 圖片廣告,文案用 config/simage_copies.json。

- 圖:從 DRIVE_FOLDER_ID 讀(用 SA),依 createdTime 由舊到新排序。
- 文案:config/simage_copies.json(S.IMAGE 1..N),依順序與圖 1:1 配對。
- 結構:ABO 圖片 campaign;每 ad set ≤ PER_ADSET(3)張;台灣 · 30-55 · 繁中(locale 22) · 手動版位。
- 合規/預算/開 ACTIVE 全部沿用 launch_static_ads 的做法。
- DRY_RUN=true:只印「圖 ↔ 文案」配對,不建。先跑這個確認 SA 讀得到、配對對不對。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, GOOGLE_SA_JSON, DRIVE_FOLDER_ID, PAGE_ID, LANDING_URL …
"""
import os, json, tempfile
import config as C
import launch as L
import naming as N
import launch_static_ads as LS
from facebook_business.adobjects.adaccount import AdAccount

FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
PER_ADSET = int(os.environ.get("VIDEOS_PER_ADSET") or 3)
DATA = os.path.join(C.ROOT, "config", "simage_copies.json")


def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def list_images(svc):
    q = f"'{FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false"
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, fields="nextPageToken, files(id,name,createdTime)",
                             pageToken=tok, pageSize=100).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    out.sort(key=lambda f: f.get("createdTime", ""))   # 舊→新
    return out


def download(svc, fid, path):
    from googleapiclient.http import MediaIoBaseDownload
    req = svc.files().get_media(fileId=fid)
    with open(path, "wb") as f:
        dl = MediaIoBaseDownload(f, req, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    svc = drive_service()
    imgs = list_images(svc)
    copies = json.load(open(DATA, encoding="utf-8"))
    pairs = list(zip(imgs, copies))     # 依順序 1:1 配對(取兩者較短的長度)
    print(f"[drive-static] 圖 {len(imgs)} 張 · 文案 {len(copies)} 則 → 配對 {len(pairs)} 組 | DRY_RUN={C.DRY_RUN}")
    for img, cp in pairs:
        print(f"  {img['name'][:42]:42s}  ↔  #{cp['n']} {cp['headline']}")
    if len(imgs) != len(copies):
        print(f"  ⚠️ 圖與文案數量不一致(圖 {len(imgs)} / 文案 {len(copies)}),只配對前 {len(pairs)} 組。")
    if not pairs:
        print("  沒有可配對的素材,結束。")
        return
    if C.DRY_RUN:
        print("  （DRY:只讀,未建廣告）")
        return

    L.ensure_page_advertiser()
    winners = C.fb_retry(L.find_winner_ads, account, C.WINNER_AD_KEYWORDS)
    if not winners:
        raise SystemExit("找不到合規來源(贏家 ad set),無法建容器。")
    src = winners[0]["adset_id"]
    cname = N.campaign_name("Image")
    L.delete_existing_campaigns(account, cname)
    camp = C.fb_retry(account.create_campaign, params={
        "name": cname, "objective": C.OBJECTIVE, "special_ad_categories": [],
        "status": "PAUSED", "is_adset_budget_sharing_enabled": False,
    })["id"]
    print(f"  ✓ ABO campaign {camp}: {cname}（{LS.ADSET_BUDGET:.0f} TWD/組）")

    groups = [pairs[i:i + PER_ADSET] for i in range(0, len(pairs), PER_ADSET)]
    n = 0
    for gi, g in enumerate(groups, 1):
        adset_id = LS.make_abo_adset(account, camp, src, f"組{gi}")
        print(f"  ── 組{gi} ad set {adset_id}(台灣 · 30-55 · 繁中 · 手動版位）")
        for img, cp in g:
            name = N.ad_name("IMG", cp["n"], cp["headline"])
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, (img["name"] or "img").replace("/", "_"))
                try:
                    download(svc, img["id"], p)
                    h = LS.upload_image(account, p)
                    ad_id = LS.create_image_ad(account, adset_id, h,
                                               cp["primary_text"], cp["headline"], name)
                    n += 1
                    print(f"     ✓ {name}  ad={ad_id}")
                except Exception as e:
                    print(f"     ⚠️ {name} 失敗: {e}")
    print(f"→ 已建 {n}/{len(pairs)} 張靜圖廣告於 ABO campaign(PAUSED)。")
    if LS.ACTIVATE and n == len(pairs):
        LS.activate_all(camp)
    elif LS.ACTIVATE:
        print(f"  ⚠️ 只建了 {n}/{len(pairs)},先不自動開 ACTIVE,留 PAUSED。")


if __name__ == "__main__":
    run()
