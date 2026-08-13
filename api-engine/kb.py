"""
素材知識庫 / 去重與編號(存 reports/creatives_kb.json,不放進廣告名)。

- 廣告名不再放 [gd:<fileId>] 那種標記;改用這個檔記錄「哪個 Drive 檔已上、對應第幾號」。
- 編號規則:檔名有標號(V5、image 3、開頭數字)就用它;沒有就自動補 1..N。
"""
import json, os, re

_HERE = os.path.dirname(os.path.abspath(__file__))
# 每個市場一份 KB,避免 MY 上過的影片被 SG 誤判為「已上」而跳過。
_MARKET = (os.environ.get("MARKET") or "MY").upper()
KB_PATH = os.path.join(os.path.dirname(_HERE), "reports", f"creatives_kb_{_MARKET}.json")


def load():
    try:
        return json.load(open(KB_PATH, encoding="utf-8"))
    except Exception:
        return {"files": {}}


def save(kb):
    os.makedirs(os.path.dirname(KB_PATH), exist_ok=True)
    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=1)


def done_ids(kb):
    return set(kb.get("files", {}).keys())


def explicit_num(fname):
    """從檔名抓明確編號(V5 / image 3 / 開頭 3_ )。抓不到回 None(不亂抓日期數字)。"""
    for pat in (r'[Vv](\d{1,3})\b',
                r'(?:image|img|圖|图|第)[\s_\-]*?(\d{1,3})',
                r'^\s*(\d{1,3})[\s_.\-]'):
        m = re.search(pat, fname or "", re.I)
        if m:
            return int(m.group(1))
    return None


def number_batch(files):
    """files: [{'id','name'},...] → {id: number}。有標號用標號,其餘自動補 1..N。"""
    nums, used = {}, set()
    for f in files:
        n = explicit_num(f.get("name", ""))
        if n and n not in used:
            nums[f["id"]] = n
            used.add(n)
    nxt = 1
    for f in files:
        if f["id"] in nums:
            continue
        while nxt in used:
            nxt += 1
        nums[f["id"]] = nxt
        used.add(nxt)
    return nums


def record(kb, fid, kind, num, ad_id, adname, fname):
    kb.setdefault("files", {})[fid] = {
        "kind": kind, "num": num, "ad_id": ad_id, "name": adname, "fname": fname}
