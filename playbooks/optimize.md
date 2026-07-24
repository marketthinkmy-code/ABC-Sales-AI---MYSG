# Playbook 03 — 自动跑 / 每日优化 (Optimize) ⭐

**目的**:每天拉數據 → 套 `config/optimization_rules.yaml` → 自動關 loser、加碼 winner。
**執行者**:Claude Code Routine(每日排程,見 `routines/daily-optimize.md`)。
**這就是「自動跑」的核心。**

---

## 每日流程

### Step 1 — 拉數據
`ads_get_ad_entities`
- level: `campaign`(先看 campaign,需要再下鑽 adset/ad)
- ad_account_id: 從 launch_template
- fields: `["id","name","status","daily_budget","spend","results","cost_per_result","ctr","cpm","impressions"]`
- date_preset: `last_3d`(近 3 天,避免單日噪音)
- filtering: `status = ACTIVE`

### Step 2 — 套規則 (讀 optimization_rules.yaml)
對每個 entity 依序判斷:

| 檢查 | 條件 | 動作 |
|---|---|---|
| 觀察期 | `spend < 40` | ⏸️ 跳過,還在學習 |
| 🔴 零轉換 | `spend ≥ 70 且 results = 0` | PAUSE |
| 🔴 CPL 過高 | `cost_per_result > 60` | PAUSE |
| 🟢 CPL 好 | `cost_per_result < 35 且 spend ≥ 100` | 預算 +20%(≤320) |
| 🟢 CPL 極佳 | `cost_per_result < 25 且 results ≥ 5` | DUPLICATE |
| ♻️ 連贏素材 | ad CPL <30 連 3 天 | 標記做變體 |

> 門檻取自 Soo Cheng 實跑分界(PAUSED 都 ≥63,ACTIVE 都 ≤35)。

### Step 3 — 執行動作
- PAUSE:`ads_update_entity`(status → PAUSED)
- 加預算:`ads_update_entity`(daily_budget × 1.2,不超過 320)
- DUPLICATE:`ads_create_campaign/ad_set/ad` 複製設定,新預算 100,PAUSED 後開

### Step 4 — 保護欄檢查 (執行前)
- 單次 PAUSE 超過 `max_pauses_per_run`(10)→ **停手,只報警不執行**。
- `dry_run: true` 時 → 只產出「建議清單」寫進 Notion,不真的改。
- 驗證 3–5 天結果符合預期後,才把 `dry_run` 改 `false`。

### Step 5 — 寫報表
把今天的 {關掉幾支、加碼幾支、總花費、平均 CPL、贏家素材} 寫進 Notion(見 `report.md`)。

---

## 首次上線建議
1. 第 1 週 `dry_run: true`,每天看它的建議對不對(跟你手動判斷比)。
2. 對得上 → 改 `dry_run: false`,讓它真的動手。
3. 之後每週回看門檻是否要微調(CPL 目標隨 offer 變)。
