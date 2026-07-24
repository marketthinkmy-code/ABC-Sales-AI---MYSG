# Routine — 每日自動優化排程

把下面的 prompt 掛成 **Claude Code Routine**(定時觸發),系統就會每天自己跑優化。

## 如何掛
在這個 session 對 Claude 說:
> 「幫我建一個每天早上 9 點(馬來西亞時間)的 Routine,prompt 用 routines/daily-optimize.md 裡的內容。」

Claude 會用 `create_trigger` 建排程(cron 以 UTC 計:MYT 09:00 = UTC 01:00 → `0 1 * * *`)。
排程會 fire 回這個 session,Claude 讀 repo 的 config + playbooks 後自動執行。

---

## Routine Prompt(排程每天送進來的訊息)

```
執行每日廣告優化。步驟:

1. 讀 config/optimization_rules.yaml 和 config/launch_template.yaml。
2. 用 ads_get_ad_entities 拉目標帳號 last_3d、status=ACTIVE 的 campaign 數據
   (fields: id,name,status,daily_budget,spend,results,cost_per_result,ctr)。
3. 照 playbooks/optimize.md 的規則表判斷每支要 PAUSE / 加預算 / DUPLICATE / 跳過。
4. 先檢查保護欄:若 dry_run=true,只產建議清單不動手;
   若要 PAUSE 超過 max_pauses_per_run,停手並回報異常。
5. 執行動作(ads_update_entity 等)。
6. 照 playbooks/report.md 把結果寫進 Notion「ABC Ads Daily」。
7. 回報今天:關了幾支、加碼幾支、總花費、平均 CPL、最佳角度、待做變體素材。

若目標帳號 is_ads_mcp_enabled=false,不要執行,直接回報帳號未啟用 MCP。
```

---

## 注意
- 首週保持 `optimization_rules.yaml` 的 `dry_run: true`,人工核對建議準確度。
- Routine fire 回同一個 session,repo 內容它讀得到。
- 若換帳號或改門檻,只改 config,不用改 Routine。
- 停用:叫 Claude 用 `delete_trigger` 移除,或 `update_trigger` 改時間。
