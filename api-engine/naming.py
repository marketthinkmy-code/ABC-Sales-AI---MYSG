"""統一命名規範(英文 · 依市場)。

  Campaign = "(MY) AI EMPLOYEE BLUEPRINT MASTERCLASS - LEAD Video - 13-AUG26"
  Ad Set   = "興趣 · 年齡 · Placement"
  Ad       = "(MY) AI EMPLOYEE BLUEPRINT MASTERCLASS | VID | #3 | Theme"

你的命名慣例:(國家) 課程名 - (objective) - 日期。
前綴/objective 標籤可用 Secret 覆蓋:NAMING_PREFIX / NAMING_OBJECTIVE。
"""
import datetime as dt
import config as C

PREFIX = C._get("NAMING_PREFIX", "") or f"({C.MARKET}) AI EMPLOYEE BLUEPRINT MASTERCLASS"
OBJ_TAG = C._get("NAMING_OBJECTIVE", "") or "LEAD"   # 命名裡的 objective 標籤(慣例用 LEAD)


def today_tag(date=None):
    d = date or dt.date.today()
    return d.strftime("%d-%b%y").upper()   # 13-AUG26


def campaign_name(media, date=None):
    """media: 'Image' 或 'Video'"""
    return f"{PREFIX} - {OBJ_TAG} {media} - {today_tag(date)}"


def ad_name(kind, num, theme):
    """kind: 'IMG' 或 'VID';num: 數字;theme: 標題"""
    theme = (theme or "").strip()
    return f"{PREFIX} | {kind} | #{num} | {theme}"


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
    interest = " / ".join(ints[:3]) if ints else "Broad"
    age = f"{t.get('age_min', '?')}-{t.get('age_max', '?')}"
    placement = "Manual Placement" if _is_manual_placement(t) else "Advantage+ Placement"
    return f"{interest} · {age} · {placement}"
