"""集中讀取設定。所有腳本共用。"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(Path(__file__).resolve().parent / ".env")


def _get(key, default=None):
    return os.environ.get(key, default)


# --- 憑證 / 帳號 ---
APP_ID = _get("META_APP_ID")
APP_SECRET = _get("META_APP_SECRET")
ACCESS_TOKEN = _get("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = _get("AD_ACCOUNT_ID", "1984262458861966")
PAGE_ID = _get("PAGE_ID")
INSTAGRAM_ID = _get("INSTAGRAM_ID") or None
PIXEL_ID = _get("PIXEL_ID")
CURRENCY = _get("CURRENCY", "TWD")

# --- 漏斗 ---
OBJECTIVE = _get("OBJECTIVE", "OUTCOME_SALES")
CONVERSION_EVENT = _get("CONVERSION_EVENT", "CompleteRegistration")
LANDING_URL = _get("LANDING_URL")

# --- 優化門檻 (數字) ---
TARGET_CPL = float(_get("TARGET_CPL", 260))
KILL_CPL = float(_get("KILL_CPL", 440))
SCALE_CPL = float(_get("SCALE_CPL", 260))
BUDGET_STEP_PCT = float(_get("BUDGET_STEP_PCT", 20))
MAX_DAILY_BUDGET = float(_get("MAX_DAILY_BUDGET", 2600))
MIN_SPEND_BEFORE_ACTION = float(_get("MIN_SPEND_BEFORE_ACTION", 280))
DRY_RUN = str(_get("DRY_RUN", "true")).lower() == "true"

ACT_ID = f"act_{AD_ACCOUNT_ID}"


def load_yaml(name):
    """讀 config/ 底下的 yaml，跟 MCP 版共用同一份設定。"""
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_api():
    """初始化 Facebook API。缺 token 就明確報錯。"""
    from facebook_business.api import FacebookAdsApi
    missing = [k for k, v in {
        "META_APP_ID": APP_ID,
        "META_APP_SECRET": APP_SECRET,
        "META_ACCESS_TOKEN": ACCESS_TOKEN,
    }.items() if not v]
    if missing:
        raise SystemExit(
            f"缺少憑證: {', '.join(missing)}。\n"
            f"請複製 api-engine/.env.example 成 .env 並填好。\n"
            f"拿 token 步驟見 api-engine/TOKEN-SETUP.md"
        )
    FacebookAdsApi.init(APP_ID, APP_SECRET, ACCESS_TOKEN)


def to_minor(amount):
    """Meta 預算用最小貨幣單位 (TWD 無小數視為整數 * 100 的慣例，SDK 用『分』)。"""
    return int(round(float(amount) * 100))
