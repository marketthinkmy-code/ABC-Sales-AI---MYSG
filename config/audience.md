# 受眾設定 — AI Employee Blueprint Masterclass (MY + SG)

實際定向由 `config/markets.yaml` + `config/angles.yaml` 帶入引擎(`api-engine`)。本文是人看的說明。

## 共用(MY / SG 相同)
- **年齡**:30–55
- **語言**:English(全英文,不投中文)
- **性別**:全部
- **版位**:Advantage+ 自動版位
- **優化事件**:Pixel `CompleteRegistration`(網站報名完成)
- **Campaign 目標**:`OUTCOME_SALES`(網站轉換)

## 依市場
| | 馬來西亞 (MY) | 新加坡 (SG) |
|---|---|---|
| 廣告帳號 | `384734236863395` | `536941169394673` |
| 投放地區 (geo) | `MY` | `SG` |
| Pixel | `605508081849922` | `952343113426537` |
| 落地頁 | `futureaiemployee.com/register-page` | `futureaiemployee.com/register-sg` |
| 幣別 | MYR | MYR |
| 強制法規 | 無 | `SINGAPORE_UNIVERSAL`(受益人/付款人 = MTC 4.0 `1038935314643355`) |

Page 共用:`460789450460649`。

## 興趣角度 (angles)
見 `config/angles.yaml`。每個 `priority: 1` 的角度 = 一支獨立 campaign,靠 CPL 賽馬。
`BROAD`(交給 Advantage+ 演算法)通常 CPL 最低,優先跑。

> ⚠️ 待確認:SG 的 CPL 天生通常比 MY 貴。目前 MY/SG 用**同一套門檻**(你指定的:<30 +20% / 30–40 +10% / 40–60 監控 / >60 關;CPA>2000 關)。
> 跑一陣子若 SG 被誤殺,可在 `markets.yaml` 的 `SG.thresholds` 單獨調高,不影響 MY。
