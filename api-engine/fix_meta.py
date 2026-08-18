"""
修正既有 campaign 的『語言 locale』與『每日預算』,並可先只讀診斷。

背景:
- 之前 locale 誤用 31(其實是葡萄牙語),要換成真正的 Chinese(Taiwan)。
- TWD 是零位小數貨幣,金額不可 ×100(500 被存成 50,000)。改成直接用原數。

DRY_RUN=true(預設): 只印出 帳號貨幣、所有 Chinese locales、抽一個 ad set 目前的 daily_budget。不改任何東西。
DRY_RUN=false: 把名稱含 MATCH 的 campaign 底下每個 ad set → locale 換成 Chinese(Taiwan)、daily_budget 設成 ADSET_BUDGET(原數,不×100)。

env: META_ACCESS_TOKEN, AD_ACCOUNT_ID, MATCH(預設 "AI獲客 ·"), ADSET_BUDGET(預設 800), DRY_RUN
"""
import os
import config as C
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.targetingsearch import TargetingSearch

MATCH = os.environ.get("MATCH", "AI獲客 ·")
ADSET_BUDGET = float(os.environ.get("ADSET_BUDGET") or 800)
DRY = (os.environ.get("DRY_RUN", "true").strip().lower() == "true")
# Meta 的零位小數貨幣:金額直接用原數,不 ×100。
ZERO_DECIMAL = {"TWD", "JPY", "KRW", "VND", "CLP", "HUF", "ISK", "UGX",
                "PYG", "XAF", "XOF", "BIF", "DJF", "GNF", "KMF", "MGA",
                "RWF", "VUV", "XPF"}


def chinese_locales():
    out, seen = [], set()
    for q in ("Chinese", "Taiwan", "Traditional", "Mandarin"):
        rows = C.fb_retry(lambda: list(TargetingSearch.search(
            params={"q": q, "type": "adlocale"})))
        for r in rows:
            key, name = int(r.get("key")), (r.get("name") or "")
            if key in seen:
                continue
            seen.add(key)
            print(f"    locale key={key}  name={name}")
            out.append((key, name))
    return out


def pick_taiwan(locs):
    for k, n in locs:
        if "Taiwan" in n or "zh_TW" in n:
            return k
    for k, n in locs:
        if "Traditional" in n:
            return k
    for k, n in locs:               # 沒有台灣/繁中細項,就用 Chinese(All)(配合 geo=TW)
        if "Chinese" in n:
            return k
    return None


def run():
    C.init_api()
    account = AdAccount(C.ACT_ID)
    cur = (C.fb_retry(lambda: AdAccount(C.ACT_ID).api_get(fields=["currency"])).get("currency") or "").upper()
    off = 1 if cur in ZERO_DECIMAL else 100
    budget_val = int(round(ADSET_BUDGET * off))
    print(f"帳號貨幣 = {cur}｜位數 offset = {off}｜{ADSET_BUDGET:.0f} {cur} → API 值 {budget_val}")
    print("Chinese locales:")
    locs = chinese_locales()
    zt = pick_taiwan(locs)
    print(f"→ Chinese(Taiwan) locale key = {zt}")

    camps = [c for c in C.fb_retry(lambda: list(account.get_campaigns(
        fields=["id", "name"], params={"limit": 300}))) if MATCH in (c.get("name") or "")]
    print(f"符合「{MATCH}」的 campaign:{len(camps)} 個")
    for c in camps:
        asets = C.fb_retry(lambda: list(Campaign(c["id"]).get_ad_sets(
            fields=["id", "name", "daily_budget", "targeting"])))
        print(f"  campaign {c['id']} {c.get('name')} — {len(asets)} 個 ad set")
        for a in asets:
            locs_now = (a.get("targeting") or {}).get("locales")
            print(f"     · {a.get('name')}｜daily_budget(raw)={a.get('daily_budget')}｜locales={locs_now}")
        if DRY:
            continue
        if zt is None:
            raise SystemExit("找不到 Chinese(Taiwan) locale,停止(不亂設語言)。")
        print(f"  campaign {c['id']} {c.get('name')}")
        for a in asets:
            tgt = a.get("targeting") or {}
            tgt["locales"] = [zt]
            params = {"targeting": tgt}
            if a.get("daily_budget"):           # 只有 ABO(ad set 有預算)才設;CBO 略過
                params["daily_budget"] = budget_val
            try:
                C.fb_retry(AdSet(a["id"]).api_update, params=params)
                print(f"     ✓ {a.get('name')}｜預算 {a.get('daily_budget')}→{params.get('daily_budget','(不動)')}｜locale→[{zt}]")
            except Exception as e:
                print(f"     ⚠️ {a['id']} 失敗: {e}")
    print("完成。" if not DRY else "（DRY:只讀,未改動）")


if __name__ == "__main__":
    run()
