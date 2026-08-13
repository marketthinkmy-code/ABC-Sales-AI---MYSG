# GitHub Secrets 清單 — ABC Sales AI · MY + SG

在 repo → Settings → Secrets and variables → Actions → New repository secret 逐一新增。
非機密值(帳號/pixel/落地頁/門檻)已在 `config/markets.yaml`,**不用**設成 Secret。

## 必填
| Secret | 用途 | 值 / 說明 |
|---|---|---|
| `META_ACCESS_TOKEN` | 操作廣告 | System User 長期 token,需能管 **MY `384734236863395` + SG `536941169394673`**,權限 `ads_management, ads_read, business_management, pages_show_list, pages_read_engagement`。步驟見 `api-engine/TOKEN-SETUP.md` |
| `META_APP_ID` / `META_APP_SECRET` | token 更安全(選填但建議) | Meta App 基本資料 |
| `DRY_RUN` | 安全閘 | **先設 `true`**(只出建議不動手)。核對 3–5 天無誤才改 `false` |

## 素材 / 文案自動化(video-pipeline · creative-pipeline · weekly CPA)
| Secret | 用途 | 值 / 說明 |
|---|---|---|
| `GOOGLE_SA_JSON` | 讀 Drive 影片 + 買單 Sheet | 服務帳號 JSON 整包。**把它的 `client_email` 共享進 Drive 素材夾 + 買單 Sheet** |
| `ANTHROPIC_API_KEY` | AI 寫文案 | Anthropic key(文案 prompt 在 `prompts/caption_system.md`) |
| `DRIVE_VIDEO_FOLDER_ID` | 影片產線 | 「直接放 mp4」的待上架資料夾 id(⚠️ 不能是壓縮包/再一層子夾) |
| `DRIVE_IMAGE_FOLDER_ID` | 圖片產線(選用) | 放圖的資料夾 id |

## 每週 CPA 戰報 + CPA>2000 自動關
| Secret | 用途 | 值 / 說明 |
|---|---|---|
| `BUYER_SHEET_ID` | 已付款學員名單 | `1cXHt9sycxKlYfv8DjeOESQyAZSvz8PSlCVBDxNMBMvg`(已當預設,可不設) |
| `PRICE_PER_SALE` | 算 ROAS | 後端課程客單價(MYR) |

## 選填(覆蓋 markets.yaml 門檻)
`TARGET_CPL` `SCALE_CPL` `MID_SCALE_MAX` `KILL_CPL` `CPA_KILL` `MAX_DAILY_BUDGET`
`START_DAILY_BUDGET` `MIN_SPEND_BEFORE_ACTION` `NAMING_PREFIX` `NAMING_OBJECTIVE`
`PACKAGE`/地區等 —— 不設就用 `config/markets.yaml` 的值。

---
### 上線順序(全程 PAUSED / DRY_RUN)
1. 設好上面必填 Secrets(`DRY_RUN=true`)。
2. `python tests/test_offline.py` 已通過(不需 token)。
3. 手動觸發 `Daily Ads Optimize`(Actions 頁按 Run)→ 看 log 印出兩市場 campaign,**不動任何東西**。
4. 用 `Video Pipeline` 的 `live=false` 試跑:列出 Drive 新影片 + AI 試寫的英文文案給你看。
5. 你核對無誤 → `live=true` 真的建(仍 PAUSED)→ Ads Manager 檢查 → 手動開 ACTIVE。
6. 每日 optimize 空跑 3–5 天對得上 → 把 `DRY_RUN` 改 `false`,正式自動。
