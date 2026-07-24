# Playbook 02 — 自动上广告 (Launch)

**目的**:把「待上架」素材，照 `config/launch_template.yaml` 自動變成 Meta 廣告。
**執行者**:Claude Code(用 Meta Ads MCP 工具),人工觸發或排程。

---

## 前置檢查
1. `config/launch_template.yaml` 的 `account.*` 三個 `FILL_ME` 已填。
2. 目標帳號 `is_ads_mcp_enabled: true`(用 `ads_get_ad_accounts` 確認)。
3. 素材已在 Google Drive「待上架」資料夾,命名符合 `docs/NAMING.md`。
4. 文案已由 `fb-ad-copy-soocheng` / `goated-ads-mtc` 技能產出。

---

## 執行順序 (每個 angle 跑一次)

對 `config/angles.yaml` 裡每個要上的 angle:

### Step 1 — 建 Campaign
`ads_create_campaign`
- name: `{brand.code} | {angle.key} | {round}` 例:`ABCSALES | BROAD | R1`
- objective: `campaign.objective` (OUTCOME_SALES)
- bid_strategy: `LOWEST_COST_WITHOUT_CAP`
- daily_budget: `ad_set.daily_budget_myr`(CBO,預算下在 campaign)
- status: **PAUSED**

### Step 2 — 建 Ad Set
`ads_create_ad_set`
- parent = 上一步 campaign_id
- optimization_goal: `OFFSITE_CONVERSIONS`
- promoted_object: { pixel_id, custom_event_type: `COMPLETE_REGISTRATION` }
- targeting: geo=`{MY,SG}`, age 25–55, `angle.detailed_targeting`, placements=advantage_plus
- status: **PAUSED**

### Step 3 — 建 Creative(每支素材一個)
先確認素材已上傳:
- 影片:`ads_get_ad_videos` 找 video_id(沒有的話先上傳)
`ads_create_creative`
- object_story_spec: { page_id, instagram_id, video_id, message=primary_text, headline, cta=SIGN_UP, link=landing_url }

### Step 4 — 建 Ad(組裝)
`ads_create_ad`
- parent = ad_set_id
- creative = 上一步 creative_id
- name: `{brand.code} | {angle.key} | {round}-{ad_no}` 例:`ABCSALES | BROAD | R1-1`
- status: **PAUSED**
- 重複 Step 3–4 直到 `launch.ads_per_adset`(3)支。

---

## 開跑 (Go Live)
1. 用 `ads_get_ad_preview` 逐支檢查素材/文案/連結正常。
2. 人工或規則確認後,用 `ads_update_entity` 把 campaign→adset→ad 狀態改成 **ACTIVE**。
3. 記錄本輪上架清單到 Notion(見 `playbooks/report.md`)。

---

## 安全原則
- **永遠先 PAUSED 再開**,別讓沒檢查的素材直接燒錢。
- 一輪先跑 `priority: 1` 的角度,穩了再展開。
- 每支素材命名帶 angle + hook 編號,優化時才知道誰在贏。
