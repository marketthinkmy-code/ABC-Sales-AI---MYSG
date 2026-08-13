"""集中讀取設定。所有腳本共用。

支援 MY / SG 雙市場:環境變數 MARKET (MY/SG) 決定用 config/markets.yaml 的哪個區塊。
優先序:GitHub Secret / env  >  markets.yaml 市場專屬  >  markets.yaml shared  >  程式預設。
機密(token / SA JSON / API key)永遠只從 env 讀,不進 markets.yaml。
"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(Path(__file__).resolve().parent / ".env")


def _get(key, default=None):
    # 空字串 (GitHub 未設的 Secret 會變空字串) 一律當作沒填，回 default。
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return default
    return val


# --- 市場選擇 -----------------------------------------------
MARKET = (_get("MARKET", "MY") or "MY").upper()


def _load_markets():
    with open(ROOT / "config" / "markets.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_M = _load_markets()
_SHARED = _M.get("shared", {}) or {}
_MARKETS = _M.get("markets", {}) or {}
if MARKET not in _MARKETS:
    raise SystemExit(
        f"未知市場 MARKET={MARKET}。config/markets.yaml 只有: {list(_MARKETS)}"
    )
_MK = _MARKETS[MARKET] or {}
_TH = {**(_SHARED.get("thresholds") or {}), **(_MK.get("thresholds") or {})}


def _mv(key, env_key, default=None):
    """市場值:env/Secret > 市場專屬 > shared > default。"""
    return _get(env_key, _MK.get(key, _SHARED.get(key, default)))


def _thv(key, env_key, default):
    """門檻值(數字):env/Secret > thresholds(市場覆蓋 shared) > default。"""
    return float(_get(env_key, _TH.get(key, default)))


# --- 憑證(機密,只從 env/Secret 讀) --------------------------
APP_ID = _get("META_APP_ID")
APP_SECRET = _get("META_APP_SECRET")
ACCESS_TOKEN = _get("META_ACCESS_TOKEN")

# --- 帳號 / 資產(非機密,markets.yaml 為主,Secret 可覆蓋) ----
AD_ACCOUNT_ID = _mv("ad_account_id", "AD_ACCOUNT_ID")
PAGE_ID = _mv("page_id", "PAGE_ID")
BUSINESS_ID = _mv("business_id", "BUSINESS_ID", "1038935314643355")
INSTAGRAM_ID = _mv("instagram_id", "INSTAGRAM_ID") or None
PIXEL_ID = _mv("pixel_id", "PIXEL_ID")
CURRENCY = _mv("currency", "CURRENCY", "MYR")

# --- 漏斗 ---------------------------------------------------
OBJECTIVE = _mv("objective", "OBJECTIVE", "OUTCOME_SALES")
CONVERSION_EVENT = _mv("conversion_event", "CONVERSION_EVENT", "CompleteRegistration")
LANDING_URL = _mv("landing_url", "LANDING_URL")
# Meta 動態網址參數(用 {{...}} 巨集)。放 url_tags，Meta 才會把 campaign/adset/ad 名帶進 UTM。
URL_TAGS = _get(
    "URL_TAGS",
    "utm_source={{site_source_name}}&utm_medium={{adset.name}}"
    "&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{placement}}",
)

# --- 受眾(市場) -------------------------------------------
GEO_COUNTRIES = _MK.get("geo") or _SHARED.get("geo") or [MARKET]
AGE_MIN = int(_mv("age_min", "AGE_MIN", 30))
AGE_MAX = int(_mv("age_max", "AGE_MAX", 55))

# --- 合規(依市場) -----------------------------------------
# 全新英文帳號沒有現成「贏家」可複製 → 預設從零建 ad set(clone_source_adset 空)。
CLONE_SOURCE_ADSET = _mv("clone_source_adset", "CLONE_SOURCE_ADSET", "") or ""
# 🇸🇬 SG(及未來其他強制法規市場)的 regional regulated category + 受益人/付款人。
REGIONAL_REGULATED_CATEGORIES = _MK.get("regional_regulated_categories") or []
DSA_BENEFICIARY_ID = _mv("dsa_beneficiary_id", "DSA_BENEFICIARY_ID")
DSA_PAYER_ID = _mv("dsa_payer_id", "DSA_PAYER_ID")
# 舊台灣式文字聲明(本專案 MY/SG 用不到,留著相容)
DSA_BENEFICIARY = _get("DSA_BENEFICIARY")
DSA_PAYOR = _get("DSA_PAYOR")
# 贏家廣告用「名稱關鍵字」比對(clone 模式才用到;本專案預設不啟用)
WINNER_AD_KEYWORDS = [
    s.strip() for s in (_get("WINNER_AD_KEYWORDS", "") or "").split(",") if s.strip()
]

# --- 優化門檻 (數字, MYR) -----------------------------------
TARGET_CPL = _thv("target_cpl", "TARGET_CPL", 30)          # 目標每次報名成本
SCALE_CPL = _thv("scale_cpl", "SCALE_CPL", 30)             # CPL < 此 → +BUDGET_STEP_PCT%
BUDGET_STEP_PCT = _thv("budget_step_pct", "BUDGET_STEP_PCT", 20)
MID_SCALE_MAX = _thv("mid_scale_max", "MID_SCALE_MAX", 40)  # SCALE_CPL <= CPL < 此 → +MID_STEP_PCT%
MID_STEP_PCT = _thv("mid_step_pct", "MID_STEP_PCT", 10)
KILL_CPL = _thv("kill_cpl", "KILL_CPL", 60)                # CPL > 此 → 關
CPA_KILL = _thv("cpa_kill", "CPA_KILL", 2000)              # CPA > 此 → 關(每週 CPA 引擎)
MAX_DAILY_BUDGET = _thv("max_daily_budget", "MAX_DAILY_BUDGET", 500)
START_DAILY_BUDGET = _thv("start_daily_budget", "START_DAILY_BUDGET", 100)
MIN_SPEND_BEFORE_ACTION = _thv("min_spend_before_action", "MIN_SPEND_BEFORE_ACTION", 40)
DRY_RUN = str(_get("DRY_RUN", "true")).lower() == "true"

ACT_ID = f"act_{AD_ACCOUNT_ID}"


def load_yaml(name):
    """讀 config/ 底下的 yaml。"""
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_api():
    """初始化 Facebook API。系統使用者 token 為必填；App ID/Secret 選填。"""
    from facebook_business.api import FacebookAdsApi
    if not ACCESS_TOKEN:
        raise SystemExit(
            "缺少 META_ACCESS_TOKEN。\n"
            "請複製 api-engine/.env.example 成 .env 填 token，"
            "或在 GitHub Secrets 設定。\n"
            "拿 token 步驟見 api-engine/TOKEN-SETUP.md"
        )
    # 系統使用者 token 單獨即可運作；有 App ID/Secret 則帶上 (更安全)。
    if APP_ID and APP_SECRET:
        FacebookAdsApi.init(APP_ID, APP_SECRET, ACCESS_TOKEN)
    else:
        FacebookAdsApi.init(access_token=ACCESS_TOKEN)


def to_minor(amount):
    """Meta 預算用最小貨幣單位(SDK 用『分』)。"""
    return int(round(float(amount) * 100))
