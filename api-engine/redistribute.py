"""
把單一 ad set 裡的 N 支圖片廣告,平均拆分到同一 campaign 的 3 個 ad set,
讓每支素材各自有獨立的學習與流量機會,成效不會集中在少數幾支。

做法:
  - 在同一 campaign 內,從現有(已合規)ad set clone 出 2 個空 ad set(繼承台灣廣告主聲明)。
  - 把原 ad set 的廣告依 id 排序後 round-robin 平均分到 3 個 ad set。
  - Meta 不能改廣告所屬 ad set,所以「移動」= 在目標 ad set 用同一 creative 重建 + 刪原廣告。

用法: python redistribute.py --campaign "AI獲客-自動 | IMG | IMG1" --sets 3
"""
import argparse
import config as C
import launch as L
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad

LETTERS = ["A", "B", "C", "D", "E", "F"]


def find_campaign(account, name):
    for c in account.get_campaigns(fields=["id", "name"], params={"limit": 300}):
        if c.get("name") == name:
            return c["id"]
    return None


def ads_of(adset_id):
    out = []
    for a in AdSet(adset_id).get_ads(fields=["id", "name", "creative"], params={"limit": 200}):
        out.append({"id": a["id"], "name": a.get("name", ""),
                    "creative_id": (a.get("creative") or {}).get("id")})
    return out


def run(camp_name, n_sets):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    camp_id = find_campaign(account, camp_name)
    if not camp_id:
        raise SystemExit(f"找不到 campaign「{camp_name}」")

    sets = list(Campaign(camp_id).get_ad_sets(fields=["id", "name"], params={"limit": 50}))
    counts = sorted(((s, ads_of(s["id"])) for s in sets), key=lambda x: len(x[1]), reverse=True)
    src_set, src_ads = counts[0]
    print(f"campaign {camp_id}『{camp_name}』:{len(sets)} 個 ad set;"
          f"來源 ad set {src_set['id']} 有 {len(src_ads)} 支廣告")

    if len(sets) >= n_sets:
        print(f"  已有 {len(sets)} 個 ad set(>= {n_sets}),不再新增,只印目前分佈:")
        for s, a in counts:
            print(f"   - {s.get('name','')} ({s['id']}) : {len(a)} 支")
        return

    # 把來源 ad set 命名為 …| A,再 clone 出其餘空 ad set
    AdSet(src_set["id"]).api_update(params={"name": f"{camp_name} | A"})
    targets = [{"id": src_set["id"], "name": f"{camp_name} | A"}]
    for i in range(n_sets - len(sets)):
        nm = f"{camp_name} | {LETTERS[i + 1]}"
        nid = L.clone_compliant_adset(account, camp_id, nm, src_set["id"])
        targets.append({"id": nid, "name": nm})
        print(f"  ✓ 新 ad set {nid}（{nm}）")

    # 依 id 排序後 round-robin 平均分(相似素材會被拆到不同 ad set)
    src_ads.sort(key=lambda a: a["id"])
    tids = [t["id"] for t in targets]
    plan = {tid: [] for tid in tids}
    for i, a in enumerate(src_ads):
        plan[tids[i % len(tids)]].append(a)

    src_id = src_set["id"]
    moved = 0
    for tid, group in plan.items():
        if tid == src_id:
            continue                      # 留在來源 ad set 的不動
        for a in group:
            if not a["creative_id"]:
                print(f"  ⚠️ {a['name']} 無 creative_id,保留原廣告不移動")
                continue
            try:
                new = account.create_ad(params={
                    "name": a["name"], "adset_id": tid,
                    "creative": {"creative_id": a["creative_id"]},
                    "status": "PAUSED"})
                Ad(a["id"]).api_delete()
                moved += 1
                print(f"  → 移動「{a['name']}」到 ad set {tid}（new ad {new['id']}）")
            except Exception as e:
                print(f"  ⚠️ 移動失敗,保留原廣告 {a['id']}: {e}")

    print("\n最終分佈:")
    for t in targets:
        print(f"   - {t['name']} ({t['id']}) : {len(ads_of(t['id']))} 支")
    print(f"共移動 {moved} 支;現在 campaign 內有 {n_sets} 個 ad set,素材平均分配。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="AI獲客-自動 | IMG | IMG1")
    ap.add_argument("--sets", type=int, default=3)
    a = ap.parse_args()
    run(a.campaign, a.sets)
