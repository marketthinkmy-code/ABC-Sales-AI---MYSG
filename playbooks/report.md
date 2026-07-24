# Playbook 04 — 报表 + 回路 (Report)

**目的**:每天把結果寫進 Notion,週報彙總反哺選題,形成閉環。
**執行者**:Claude Code Routine(接在 optimize 之後跑)。

---

## 每日寫入 (Notion)
用 `notion-create-pages` 在「ABC Ads Daily」資料庫新增一筆:

| 欄位 | 來源 |
|---|---|
| 日期 | 今天 |
| 總花費 | Σ spend (last_1d) |
| 報名數 | Σ results |
| 平均 CPL | 花費 / 報名數 |
| 最佳角度 | CPL 最低的 angle |
| 關掉的廣告 | optimize 產出的 PAUSE 清單 |
| 加碼的廣告 | optimize 產出的 SCALE 清單 |
| 待做變體的素材 | creative_feedback 標記 |

> 首次需先建 Notion 資料庫(`notion-create-database`),欄位如上。

---

## 每週彙總 (回路)
每週一產週報,回答三個問題,反哺 Phase 1 選題:
1. **哪個角度 ROI 最高?** → 下週該角度多產素材。
2. **哪種 hook 贏最多?** → 用 `viral-machine-wk` 做同 hook 變體。
3. **哪些角度該淘汰?** → 從 `config/angles.yaml` 降 priority 或移除。

---

## 閉環
```
报表发现赢家角度/hook
   → viral-machine-wk 出同类选题
   → goated-ads-mtc 写脚本
   → Higgsfield 产视频
   → playbooks/launch.md 自动上架
   → 回到每日 optimize
```
