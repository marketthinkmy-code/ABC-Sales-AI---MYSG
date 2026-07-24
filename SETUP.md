# SETUP — 從 0 到 1 建 ABC Sales AI 廣告自動化

> 目標:像 Soo Cheng 那套一樣，**自動上廣告、自動優化、自動報表**。
> 本文按 Phase 0 → 4 順序做，照做就能落地。

---

## 系統全貌

```
① 素材供给         ② 自动上            ③ 自动跑            ④ 报表+回路
Higgsfield  →  Meta Ads MCP  →  Claude Code Routine  →  Notion
产视频          建 campaign        每日 kill/scale         写数据、反哺选题
              /adset/creative/ad
```

**引擎 = Claude Code Routine**(你選的):不用寫 Python、不用架伺服器，
排程每天喚醒這個 session，Claude 讀 repo 的 config + playbooks，用 Meta MCP 直接操作廣告。

---

## Phase 0 — 地基(一次性,做好不再碰)⭐ 不能跳

| # | 項目 | 怎麼做 | 完成勾 |
|---|---|---|---|
| 0.1 | 選定 ad account | 必須 `is_ads_mcp_enabled: true`。⚠️ 你截圖選的 `1984262458861966 (AI 回覆 幫你獲客)` **MCP 未啟用 + 是 TWD**，不能用。建議改用 MTC 4.0 旗下已啟用的 MYR 帳號(如 `689850610799710` SG AI 员工)。 | ☐ |
| 0.2 | Pixel + 轉換事件 | 設好 `CompleteRegistration`(=Website registrations completed)。**沒有轉換事件=不能自動優化。** | ☐ |
| 0.3 | FB Page (+IG) | 確認粉專綁到帳號(`ads_get_ad_account_pages` 查 page_id)。 | ☐ |
| 0.4 | 付款方式 | 帳號要有有效付款方式。 | ☐ |
| 0.5 | ⭐ **冠軍模板** | **先手動跑出 1 個穩定 campaign**(CPL 達標),之後自動化都是複製它換素材。沒這步 = 自動化地虧錢。 | ☐ |

> Soo Cheng 的冠軍模板已知:`OUTCOME_SALES` + Highest volume + 每興趣一 campaign + 日預算 100 起。ABC 直接沿用，只要驗證你的 offer 在這結構下 CPL 站得住。

---

## Phase 1 — 素材供給(自動化的燃料)

固定產線,產出格式統一的素材餵給系統:
```
选题 viral-machine-wk → 脚本 goated-ads-mtc → 视频 Higgsfield → 存 Google Drive「待上架」
```
- 命名照 `docs/NAMING.md`:`ABCSALES_0724_痛点恐惧_H01.mp4`
- 文案用 `fb-ad-copy-soocheng` / `goated-ads-mtc` 出，存進 launch_template。

---

## Phase 2 — 自动上(建广告)

1. 填 `config/launch_template.yaml` 的 3 個 `FILL_ME`(帳號、page、pixel、landing_url)。
2. 選要跑的角度(`config/angles.yaml`,首輪只跑 priority=1)。
3. 照 `playbooks/launch.md` 執行 → Claude 用 Meta MCP 建 campaign/adset/creative/ad(全 **PAUSED**)。
4. `ads_get_ad_preview` 檢查 → 沒問題再統一開 ACTIVE。

**觸發方式**:對 Claude 說「照 playbooks/launch.md 幫我上這批素材」即可。

---

## Phase 3 — 自动跑(每日优化)⭐ 核心

1. 檢查 `config/optimization_rules.yaml` 門檻(已按 Soo Cheng 校準:kill>60、scale<35)。
2. **首週保持 `dry_run: true`** —— 系統只出建議不動手,你核對準不準。
3. 照 `routines/daily-optimize.md` 掛 Routine:
   > 對 Claude 說:「幫我建每天 MYT 09:00 的 Routine,prompt 用 routines/daily-optimize.md。」
4. 核對 3–5 天無誤 → 改 `dry_run: false` → 系統開始真的自動關/加碼。

---

## Phase 4 — 报表 + 回路

- Optimize 跑完自動把 KPI 寫進 Notion(首次先 `notion-create-database` 建「ABC Ads Daily」)。
- 每週彙總最佳角度/hook → 反哺 Phase 1 選題,閉環。詳見 `playbooks/report.md`。

---

## 落地時程(建議 2 週)

| 時間 | 做什麼 |
|---|---|
| Week 1 前半 | Phase 0 地基 + 手動跑出冠軍模板(**最關鍵**) |
| Week 1 後半 | 填 config,測 Phase 2 自動建廣告(PAUSED 驗證) |
| Week 2 前半 | 掛 Routine,`dry_run: true` 觀察優化建議 |
| Week 2 後半 | 轉 `dry_run: false` + 接 Notion 報表,跑通閉環 |

---

## 常見卡點

| 症狀 | 原因 / 解法 |
|---|---|
| MCP 說帳號不能操作 | `is_ads_mcp_enabled: false`,換已啟用帳號或等 Meta 放行 |
| 自動優化不動作 | 沒設轉換事件(0.2),或還在觀察期(spend<40) |
| winner 被誤關 | learning 期太短,調高 `min_spend_before_action_myr` |
| 素材上了不跑量 | 目標受眾太窄,先用 BROAD 交給 Advantage+ |
| 一次關太多 | 保護欄 `max_pauses_per_run` 擋下了,先人工看發生什麼事 |
