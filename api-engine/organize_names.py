"""
一次性:把某個 campaign 依新命名規範整個改名(campaign + ad sets + ads),並寫進 KB。
- Campaign → naming.campaign_name(media)
- Ad Set   → naming.adset_name(該 ad set 的實際 targeting)
- Ad       → naming.ad_name(kind, #編號, 痛點) ;去掉舊的 [gd:...] 亂碼,依 ad 順序編 1..N

用法: python organize_names.py --media Image --match "IMG | IMG3"
"""
import argparse, re
import config as C
import kb as KB
import naming as N
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad


def _theme(cur):
    s = re.sub(r"\s*\[gd:[^\]]+\]", "", cur or "")       # 去掉 [gd:...]
    parts = [p.strip() for p in s.split("|") if p.strip()]
    return parts[-1] if parts else s.strip()


def run(media, match):
    C.init_api()
    account = AdAccount(C.ACT_ID)
    kbo = KB.load()
    adkind = "IMG" if media == "Image" else "VID"
    camps = [c for c in account.get_campaigns(fields=["id", "name"], params={"limit": 300})
             if match in (c.get("name") or "")]
    if not camps:
        raise SystemExit(f"找不到名稱含「{match}」的 campaign")
    for c in camps:
        cid = c["id"]
        newc = N.campaign_name(media)
        Campaign(cid).api_update(params={"name": newc})
        print(f"campaign {cid}: 「{c.get('name')}」 → 「{newc}」")
        for aset in Campaign(cid).get_ad_sets(fields=["id", "name", "targeting"], params={"limit": 50}):
            newa = N.adset_name(aset.get("targeting") or {})
            try:
                AdSet(aset["id"]).api_update(params={"name": newa})
                print(f"  ad set {aset['id']} → 「{newa}」")
            except Exception as e:
                print(f"  ⚠️ ad set {aset['id']} 改名失敗: {e}")
            ads = list(AdSet(aset["id"]).get_ads(fields=["id", "name"], params={"limit": 200}))
            ads.sort(key=lambda a: a["id"])
            for i, a in enumerate(ads, 1):
                cur = a.get("name", "")
                m = re.search(r"\[gd:([A-Za-z0-9_-]+)\]", cur)
                fid = m.group(1) if m else a["id"]
                newname = N.ad_name(adkind, i, _theme(cur))
                try:
                    Ad(a["id"]).api_update(params={"name": newname})
                    KB.record(kbo, fid, adkind, i, a["id"], newname, cur)
                    print(f"    ad {a['id']} → 「{newname}」")
                except Exception as e:
                    print(f"    ⚠️ ad {a['id']} 改名失敗: {e}")
    KB.save(kbo)
    print("→ 改名完成,KB 已更新。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", default="Image")
    ap.add_argument("--match", required=True)
    a = ap.parse_args()
    run(a.media, a.match)
