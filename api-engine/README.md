# Path B — Marketing API 直連引擎(給 MCP 鎖死的帳號)

**為什麼有這個**:`AI 回覆 幫你獲客 (1984262458861966, TWD)` 的 MCP 被 Meta gating 鎖死
(連讀都被擋)。但底層 Marketing API 沒鎖 —— 自己拿 token 直連,就能在這個帳號上
**完整複製 Soo Cheng(自動上 + 自動跑 + 自動複製贏家)**,不用等 Meta 放行。

## 這引擎 = Soo Cheng 那套,只是換了執行方式

| Soo Cheng 的能力 | 這裡對應 |
|---|---|
| 一角度一 campaign、CBO、Highest volume | `launch.py`(讀 `config/launch_template.yaml` + `angles.yaml`) |
| CPL 賽馬、自動關 loser (>60) | `optimize.py` 的 PAUSE 規則 |
| 自動加碼 winner (<35) | `optimize.py` 的 SCALE |
| **自動複製贏家**(native 做不到) | `optimize.py` 的 DUPLICATE ✅ |
| 每日跑 | cron / GitHub Actions 排 `optimize.py` |

門檻(kill/scale)與 MCP 版共用 `config/` 那份設定的邏輯,數字放在 `.env`(TWD)。

## 上手 4 步
1. **拿 token** → 照 `TOKEN-SETUP.md`(唯一要你做的事)。
2. `cp .env.example .env` 填 token / page / pixel / landing。
3. `pip install -r requirements.txt`
4. 跑:
   ```bash
   DRY_RUN=true python optimize.py                 # 先空跑看讀不讀得到
   python launch.py --round R1                     # 自动上(先建 PAUSED)
   # 检查无误 → .env 设 DRY_RUN=false
   python optimize.py                              # 自动跑
   ```

## 每日自動化(挑一個)
- **cron**(有自己伺服器):`0 9 * * * cd .../api-engine && python optimize.py`
- **GitHub Actions**(免伺服器):把 token 放 repo Secrets,排 workflow 每天跑 `optimize.py`。
  (要的話跟我說,我幫你補 `.github/workflows/optimize.yml`。)

## 檔案
| 檔 | 作用 |
|---|---|
| `config.py` | 讀 `.env` + `config/*.yaml`,初始化 API |
| `launch.py` | 自動上:建 campaign/adset/creative/ad(全 PAUSED) |
| `optimize.py` | 自動跑:kill / scale / duplicate |
| `.env.example` | 設定範本(複製成 `.env`) |
| `TOKEN-SETUP.md` | 拿 token 手把手步驟 |

## 和 MCP 版的關係
`config/`、`playbooks/`、`docs/NAMING.md` 是**兩個引擎共用**的邏輯與命名。
- MCP 已啟用的帳號 → 用根目錄的 MCP + Routine 方式(最省事)。
- 這個 TWD 帳號(MCP 鎖死)→ 用這個 `api-engine/`。
兩邊跑的是**同一套 Soo Cheng 策略**,只是引擎不同。
