# 如何拿 Meta Access Token(唯一需要你做的事)

Path B 全自動引擎唯一的門檻 = 一組能操作 `AI 回覆 幫你獲客` 帳號的 token。
拿到後填進 `.env`,引擎就能在這個 MCP 鎖死的帳號上自動上、自動跑。

> 為什麼這行得通:MCP 是 Meta 的「託管層」被 gating,但 Marketing API(Graph API)
> 這個底層大門對 ACTIVE 帳號一直開著。你自己拿 token 直連,就繞過 MCP 的限制。

---

## 步驟(約 15 分鐘,要 Business Manager 管理員權限)

### 1. 建一個 Meta App
- 到 https://developers.facebook.com/apps → 建立應用程式 → 類型選「Business」。
- 記下 **App ID** 和 **App Secret**(App 設定 → 基本資料)。
- 加入產品「Marketing API」。

### 2. 建 System User(系統使用者)+ 給權限
- 到 https://business.facebook.com → 商業設定 → 使用者 → **系統使用者** → 新增。
- 角色選「管理員」。
- 指派資產:把 **廣告帳號 `1984262458861966`** 指派給這個 System User,權限給「管理廣告」。
- 也把你的 **Meta App** 指派給它。

### 3. 產生長期 Token
- 在 System User 頁面 → 「產生新權杖」。
- 選你的 App。
- 勾這些權限:`ads_management`、`ads_read`、`business_management`、`pages_show_list`、`pages_read_engagement`。
- 產生 → **複製 token**(系統使用者 token 是長期的,不會過期)。

### 4. 填進 .env
```bash
cd api-engine
cp .env.example .env
# 編輯 .env,填:
#   META_APP_ID / META_APP_SECRET / META_ACCESS_TOKEN
#   PAGE_ID / PIXEL_ID / LANDING_URL
```
- PAGE_ID:商業設定 → 粉絲專頁,找綁在這帳號的專頁 ID。
- PIXEL_ID:事件管理工具 → 你的資料集 ID。

### 5. 測試通不通
```bash
pip install -r requirements.txt
DRY_RUN=true python optimize.py     # 應該印出目前 campaign,不會動到任何東西
```
印得出東西 = token 通了。接著就能跑 `launch.py` 上廣告。

---

## 安全
- **token 等於帳號鑰匙,絕不能 commit 進 git。** `.env` 已被 `.gitignore` 擋住。
- 只給必要權限(`ads_management` 範圍限這一個帳號)。
- 之後要停,回 System User 頁面撤銷 token 即可。

---

## 我做不到的部分
拿 token 這步需要**你的 Business Manager 帳密登入**,我(Claude)無法代登、無法代產。
但上面每一步我都寫清楚了,你或你的工程師照做即可;卡住把畫面截圖給我,我帶你過。
