# ABC Sales AI — MY/SG Ads Automation

從 0 到 1 的 Facebook/Meta 廣告自動化系統 —— **自動上廣告、自動優化、自動報表**。
模板來自 Soo Cheng (StockBloom) 已驗證在跑的結構,移植到 ABC Sales AI。

## 這套系統做什麼

```
① 素材供给   →   ② 自动上(建广告)   →   ③ 自动跑(每日优化)   →   ④ 报表+回路
  Higgsfield        Meta Ads MCP           Claude Code Routine       Notion
```

- **自動上**:丟素材 + 填 config → 系統照「冠軍模板」自動建 campaign / ad set / creative / ad。
- **自動跑**:每天定時拉數據 → 套 kill/scale 規則 → 自動關 loser、加預算給 winner。
- **報表**:每日把 KPI 與贏家素材寫進 Notion,反哺選題。

## 目錄結構

| 路徑 | 內容 |
|---|---|
| `SETUP.md` | ⭐ 從 0 到 1 的完整落地步驟(先讀這個) |
| `config/launch_template.yaml` | 冠軍模板:目標/受眾/預算/版位 |
| `config/angles.yaml` | 興趣角度清單(每角度一個 campaign) |
| `config/optimization_rules.yaml` | kill / scale / duplicate 門檻 |
| `playbooks/launch.md` | 自動上廣告的執行步驟(Meta MCP 調用順序) |
| `playbooks/optimize.md` | 每日優化引擎的規則與操作 |
| `playbooks/report.md` | 每日報表寫入 Notion |
| `routines/daily-optimize.md` | 掛給 Claude Code Routine 的排程 prompt |
| `docs/NAMING.md` | 命名規範(自動化能讀懂素材的關鍵) |

## 快速開始

1. 讀 `SETUP.md`,完成 Phase 0 地基。
2. 填好 `config/launch_template.yaml` 的 3 個必填變數(帳號、page、pixel)。
3. 用 `playbooks/launch.md` 上第一批廣告(先 PAUSED 檢查再開)。
4. 用 `routines/daily-optimize.md` 掛每日排程,系統開始自動跑。

## 兩種引擎(依帳號 MCP 狀態選)

| 帳號 MCP | 引擎 | 位置 |
|---|---|---|
| ✅ 已啟用(如 MTC 4.0 旗下 MYR 帳號) | Claude + Meta MCP + Routine(最省事) | 根目錄 `playbooks/` + `routines/` |
| ❌ 鎖死(如 `AI 回覆 幫你獲客` TWD) | Marketing API 直連 Python(自己拿 token) | `api-engine/` |

兩種引擎跑的是**同一套 Soo Cheng 策略**,共用 `config/`、`docs/NAMING.md`。
`AI 回覆 幫你獲客` 帳號 MCP 被 Meta 鎖死(連讀都被擋)→ 走 `api-engine/`,見 `api-engine/README.md`。
