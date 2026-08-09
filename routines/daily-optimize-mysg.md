# Routine — 每日自動優化【AI 員工 幫你做工 MY + SG】

一個 Routine 同時管兩個帳戶,各用各的門檻。

## 如何掛
在這個 session 對 Claude 說:
> 「幫我建每天 MYT 09:00 的 Routine,prompt 用 routines/daily-optimize-mysg.md 裡的內容。」

(cron 以 UTC 計:MYT 09:00 = UTC 01:00 → `0 1 * * *`)

---

## Routine Prompt(排程每天送進來的訊息)

```
執行「AI 員工 幫你做工」每日廣告優化,兩個帳戶依序跑:

【MY】帳戶 1578372656904971
  - config: config/launch_template_my.yaml + config/optimization_rules.yaml(預設 MYR 門檻 35/60)
【SG】帳戶 689850610799710
  - config: config/launch_template_sg.yaml + config/optimization_rules_sg.yaml(SG 專用門檻 55/85)

每個帳戶的步驟:
1. 讀對應的 launch_template 和 optimization_rules。
2. 用 ads_get_ad_entities 拉 last_3d、ACTIVE 的 ad 數據
   (fields: id,name,amount_spent,cost_per_omni_complete_registration,
    omni_complete_registration,ctr,effective_status)。
3. 照 playbooks/optimize.md 的規則表判斷每支要 PAUSE / 加預算 / DUPLICATE / 跳過。
   ⚠️ 用該帳戶自己的門檻 —— 不要拿 MY 的 35/60 去殺 SG 的廣告。
4. 檢查保護欄:dry_run=true 只出建議;要 PAUSE 超過 max_pauses_per_run 就停手回報。
5. 執行動作(ads_update_entity 等)。
6. 照 playbooks/report.md 把兩個帳戶各寫一行進 Notion「AI Employee Ads Daily」。
7. 回報:每個帳戶關了幾支、加碼幾支、總花費、平均 CPL、對比 docs/WINNERS-AI-EMPLOYEE.md
   有沒有新素材打進 winner 段位。

若任一帳戶 is_ads_mcp_enabled=false 或 status 不是 ACTIVE(如 UNSETTLED 帳單問題),
跳過該帳戶並在回報裡標紅 —— 帳單問題要人工處理,不是優化問題。
```

---

## 注意
- 首週兩份 rules 都保持 `dry_run: true`,人工核對 3-5 天。
- SG 帳號目前幾乎全停,先照 playbooks/launch.md 用 launch_template_sg.yaml 重啟,再掛優化。
- 兩個帳戶曾出現 UNSETTLED(帳單刷不過)—— Routine 每天第一步等於免費幫你盯帳單狀態。
