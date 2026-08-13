# 命名規範 (Naming Convention)

自動化能不能「讀懂」廣告在贏什麼,全靠命名一致。照 Soo Cheng 的格式。

## 素材檔名 (Google Drive)
```
{BRAND}_{日期MMDD}_{角度}_{Hook編號}.mp4
例:ABCSALES_0724_痛点恐惧_H01.mp4
```
- 角度:痛点恐惧 / 权威背书 / 结果展示 / 好奇钩子 …
- Hook 編號:H01, H02 …(同角度不同開頭)

## Campaign / Ad Set / Ad
照 Soo Cheng 的 `BRAND | ANGLE | 版本` 格式:

| 層級 | 格式 | 範例 |
|---|---|---|
| Campaign | `{BRAND} \| {ANGLE} \| {ROUND}` | `ABCSALES \| BROAD \| R1` |
| Ad Set | 同 campaign 名(1 campaign : 1 adset) | `ABCSALES \| BROAD \| R1` |
| Ad | `{BRAND} \| {ANGLE} \| {ROUND}-{編號}` | `ABCSALES \| BROAD \| R1-1` |

> Soo Cheng 尾碼 `1-1-3` = 1 campaign : 1 adset : 3 ads。ABC 沿用「一角度一 campaign、每組 3 支素材賽馬」。

## 為什麼重要
- 報表能 group by 角度 → 知道哪個受眾贏。
- 能 group by Hook → 知道哪種開頭贏 → 反哺選題。
- ROUND(R1/R2)標示第幾輪素材 → 追蹤迭代。
