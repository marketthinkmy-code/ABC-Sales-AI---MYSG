"""離線測試(不連 Meta):驗證 markets.yaml 讀取 + optimize 分档門檻。

跑法: python tests/test_offline.py
只需要 PyYAML / python-dotenv(+ optimize 測試需要 facebook-business 可 import)。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api-engine"))


def load_config(market):
    os.environ["MARKET"] = market
    for m in ("config", "optimize", "naming", "launch"):
        sys.modules.pop(m, None)
    import config as C
    return C


def test_markets():
    my = load_config("MY")
    assert my.MARKET == "MY"
    assert my.AD_ACCOUNT_ID == "384734236863395", my.AD_ACCOUNT_ID
    assert my.PIXEL_ID == "605508081849922", my.PIXEL_ID
    assert my.LANDING_URL.endswith("/register-page"), my.LANDING_URL
    assert my.PAGE_ID == "460789450460649"          # shared
    assert my.GEO_COUNTRIES == ["MY"], my.GEO_COUNTRIES
    assert my.OBJECTIVE == "OUTCOME_SALES"
    assert my.CONVERSION_EVENT == "CompleteRegistration"
    assert my.AGE_MIN == 30 and my.AGE_MAX == 55
    assert my.CURRENCY == "MYR"
    assert (my.SCALE_CPL, my.MID_SCALE_MAX, my.KILL_CPL) == (30, 40, 60)
    assert my.MID_STEP_PCT == 10 and my.BUDGET_STEP_PCT == 20
    assert my.CPA_KILL == 2000
    assert not my.REGIONAL_REGULATED_CATEGORIES

    sg = load_config("SG")
    assert sg.AD_ACCOUNT_ID == "536941169394673", sg.AD_ACCOUNT_ID
    assert sg.PIXEL_ID == "952343113426537", sg.PIXEL_ID
    assert sg.LANDING_URL.endswith("/register-sg"), sg.LANDING_URL
    assert sg.PAGE_ID == "460789450460649"          # shared
    assert sg.GEO_COUNTRIES == ["SG"], sg.GEO_COUNTRIES
    assert "SINGAPORE_UNIVERSAL" in sg.REGIONAL_REGULATED_CATEGORIES
    assert sg.DSA_BENEFICIARY_ID == "1038935314643355"
    assert sg.DSA_PAYER_ID == "1038935314643355"
    print("✓ markets.yaml MY/SG 讀取正確")


def test_decide_bands():
    load_config("MY")
    import optimize as O

    def r(cpl, spend=200, results=10):
        return {"cpl": cpl, "spend": spend, "results": results,
                "daily_budget": 100, "id": "1", "name": "x"}

    cases = {
        25: "SCALE",        # CPL < 30 → +20%
        35: "SCALE_MID",    # 30 ≤ CPL < 40 → +10%
        50: "KEEP",         # 40–60 監控
        70: "PAUSE",        # > 60 關
        15: "DUPLICATE",    # < 0.7×30=21 且 報名≥5 → 複製
    }
    for cpl, want in cases.items():
        got = O.decide(r(cpl))[0]
        assert got == want, f"CPL {cpl}: 期望 {want} 得到 {got}"
    assert O.decide(r(35, spend=10))[0] == "SKIP"          # 未達 min spend 40
    assert O.decide(r(None, spend=200, results=0))[0] == "PAUSE"  # 零成果燒 >2×target
    print("✓ optimize 分档門檻正確 (<30 +20% / 30-40 +10% / 40-60 監控 / >60 關)")


if __name__ == "__main__":
    test_markets()
    try:
        test_decide_bands()
    except ImportError as e:
        print(f"(略過 optimize 測試,facebook-business 未安裝: {e})")
    print("✅ 離線測試通過")
