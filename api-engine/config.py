"""集中讀取設定。所有腳本共用。"""
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


# --- 憑證 / 帳號 ---
APP_ID = _get("META_APP_ID")
APP_SECRET = _get("META_APP_SECRET")
ACCESS_TOKEN = _get("META_ACCESS_TOKEN")
# 帳號/Page/Pixel 不是機密，直接用 discover 撈到的值當預設(Secret 有填則覆蓋)。
AD_ACCOUNT_ID = _get("AD_ACCOUNT_ID", "1984262458861966")
PAGE_ID = _get("PAGE_ID", "1024532770753639")
INSTAGRAM_ID = _get("INSTAGRAM_ID") or None
PIXEL_ID = _get("PIXEL_ID", "1338102884859245")
CURRENCY = _get("CURRENCY", "TWD")

# --- 漏斗 ---
OBJECTIVE = _get("OBJECTIVE", "OUTCOME_SALES")
CONVERSION_EVENT = _get("CONVERSION_EVENT", "CompleteRegistration")
LANDING_URL = _get("LANDING_URL", "https://futureaiemployee.com/ai-closer-register")
# Meta 動態網址參數(用 {{...}} 巨集)。放 url_tags，Meta 才會把 campaign/adset/ad 名帶進 UTM。
URL_TAGS = _get(
    "URL_TAGS",
    "utm_source={{site_source_name}}&utm_medium={{adset.name}}"
    "&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{placement}}",
)
# 台灣法規：廣告主/付款方(來自 Business Manager 已驗證的實體)。
# 建 TW ad set 時帶上，否則 Meta 擋「No advertiser information for Taiwan ads」。
DSA_BENEFICIARY = _get("DSA_BENEFICIARY", "ABC SALESBOT SDN. BHD.")
DSA_PAYOR = _get("DSA_PAYOR", "ABC SALESBOT SDN. BHD.")

# --- 優化門檻 (數字, TWD) ---
# 依 AI 回覆 幫你獲客 帳號設定：目標 CPA 180，可接受到 240。
# Secret 有填就用 Secret，沒填就用這裡的預設(這些不是機密，放預設即可)。
TARGET_CPL = float(_get("TARGET_CPL", 180))
KILL_CPL = float(_get("KILL_CPL", 240))       # CPA 高於此 → 關 (你說可接受到 240)
SCALE_CPL = float(_get("SCALE_CPL", 180))     # CPA 低於此 → 加預算
BUDGET_STEP_PCT = float(_get("BUDGET_STEP_PCT", 20))
MAX_DAILY_BUDGET = float(_get("MAX_DAILY_BUDGET", 2600))
MIN_SPEND_BEFORE_ACTION = float(_get("MIN_SPEND_BEFORE_ACTION", 180))
DRY_RUN = str(_get("DRY_RUN", "true")).lower() == "true"

ACT_ID = f"act_{AD_ACCOUNT_ID}"


def load_yaml(name):
    """讀 config/ 底下的 yaml，跟 MCP 版共用同一份設定。"""
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
    """Meta 預算用最小貨幣單位 (TWD 無小數視為整數 * 100 的慣例，SDK 用『分』)。"""
    return int(round(float(amount) * 100))
