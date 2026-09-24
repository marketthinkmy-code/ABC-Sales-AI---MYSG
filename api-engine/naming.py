"""
統一命名規範:
  Campaign  = 「AI獲客 · Image/Video · 8月9號2026」  (品牌 · 素材類型 · 建立日期)
  Ad Set    = 「受眾興趣 · 年齡 · Placement」        (版位全開=Advantage+ Placement / 有篩選=Manual Placement)
  Ad        = 「AI獲客 | IMG/VID | #編號 | 痛點標題」  (乾淨、帶編號、無亂碼)
"""
import datetime as dt

BRAND = "AI獲客"


def today_zh():
    d = dt.date.today()
    return f"{d.month}月{d.day}號{d.year}"


def campaign_name(media, date=None):
    """media: 'Image' 或 'Video'"""
    return f"{BRAND} · {media} · {date or today_zh()}"


def ad_name(kind, num, theme):
    """kind: 'IMG' 或 'VID';num: 數字;theme: 痛點標題"""
    theme = (theme or "").strip()
    return f"{BRAND} | {kind} | #{num} | {theme}"


def _interests(t):
    out = []
    for spec in (t.get("flexible_spec") or []):
        for it in (spec.get("interests") or []):
            if it.get("name"):
                out.append(it["name"])
    for it in (t.get("interests") or []):
        name = it.get("name") if isinstance(it, dict) else it
        if name:
            out.append(name)
    # 去重保序
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _is_manual_placement(t):
    keys = ("publisher_platforms", "facebook_positions", "instagram_positions",
            "messenger_positions", "audience_network_positions", "device_platforms")
    return any(t.get(k) for k in keys)


def adset_name(targeting):
    t = targeting or {}
    ints = _interests(t)
    interest = "、".join(ints[:3]) if ints else "廣泛 Broad"
    age = f"{t.get('age_min', '?')}-{t.get('age_max', '?')}"
    placement = "Manual Placement" if _is_manual_placement(t) else "Advantage+ Placement"
    return f"{interest} · {age} · {placement}"
