# XAUUSD SMC Trading Bot — IC Markets MT5

A fully autonomous **XAUUSD (Gold)** trading bot built in Python on top of the
[MetaTrader5](https://pypi.org/project/MetaTrader5/) library. It uses a
deterministic, rule-based **Smart Money Concepts (SMC)** strategy — top-down bias,
liquidity sweeps, order blocks, and fair value gaps — with strict risk management,
a New York session filter, and a red-folder news filter.

> ⚠️ **Real-money software.** This bot can place live trades. Always run it on a
> **demo account first** (the default) and understand every parameter before
> switching to live. Trading leveraged instruments carries a high risk of loss.

---

## Strategy in a nutshell

The bot performs a **top-down analysis** every cycle:

1. **HTF Bias (H1)** — Higher Highs + Higher Lows = bullish; Lower Highs + Lower
   Lows = bearish. Only trades in the direction of bias; skips when ranging.
2. **Liquidity Sweep (M15)** — Looks for a wick that pierces the previous NY
   session high/low and closes back inside, *against* the bias, within the last
   8 candles.
3. **Order Block (M15)** — The last opposite candle before a 3+ candle impulse,
   aligned with bias, that price has not yet returned to.
4. **Fair Value Gap (M5)** — A 3-candle price imbalance inside the order block,
   aligned with bias. Entry triggers when price enters the FVG.
5. **Entry** — Placed only when **all** conditions are true, the NY session is
   open, no red news is near, no trade is already open, and the daily loss limit
   has not been hit.

Stop loss is built from recent M15 swings (+ buffer), take profit targets 1:3 RR
(extended to 1:4 when previous-session liquidity lies beyond), and position size
risks a fixed `RISK_PERCENT` of the account per trade.

---

## File structure

| File | Purpose |
| --- | --- |
| `main.py` | Entry point, runs the main loop |
| `strategy.py` | All SMC logic: `bias()`, `sweep()`, `order_block()`, `fvg()`, `signal()` |
| `risk.py` | Position sizing, daily loss limit, scaling logic, lot calculation |
| `news.py` | ForexFactory fetch, red event filter, safe-mode fallback |
| `mt5_client.py` | All MT5 interactions: connect, candles, orders, balance, positions |
| `config.py` | All settings loaded from `.env`, all parameters in one place |
| `utils.py` | Logging functions, time helpers, console status printer |
| `.env.example` | Template with placeholder values |
| `requirements.txt` | Python dependencies |
| `README.md` | This guide |

---

## Setup — step by step

### 1. Install MetaTrader 5 from IC Markets

1. Open an IC Markets account at <https://www.icmarkets.com/> (start with a
   **demo** account).
2. Download the **MetaTrader 5** desktop terminal from the IC Markets website
   (Trading Platforms → MetaTrader 5).
3. Install it on a **Windows** machine (the `MetaTrader5` Python package only
   works on Windows, or Windows under a VPS).
4. Log in to the terminal with your demo credentials and **leave it running**.
   The bot attaches to this already-running, logged-in terminal.

### 2. Install Python 3.10+

1. Download Python **3.10 or newer** from <https://www.python.org/downloads/>.
2. During installation, tick **“Add Python to PATH”**.
3. Verify in a terminal:
   ```bash
   python --version
   ```

### 3. Install dependencies

From inside the `xauusd_smc_bot` folder:

```bash
pip install -r requirements.txt
```

### 4. Configure your `.env` file

1. Copy the template:
   ```bash
   copy .env.example .env      # Windows
   # cp .env.example .env      # macOS/Linux
   ```
2. Edit `.env` and fill in your MT5 login details:
   ```ini
   MT5_LOGIN=12345678
   MT5_PASSWORD=your-password-here
   MT5_SERVER=ICMarketsSC-Demo
   ```
   - Demo server: `ICMarketsSC-Demo`
   - Live server: `ICMarketsSC-Live`

### 5. Run the bot

Make sure the MT5 terminal is **running and logged in**, then:

```bash
python main.py
```

You should see the status block print every 5 minutes:

```
==========================================
XAUUSD SMC BOT — IC Markets MT5
Time (EST):     09:45am
Session:        OPEN
News:           CLEAR
HTF Bias:       BULLISH
Sweep Detected: YES
OB Zone:        3285.50 – 3287.20
FVG Active:     YES
Signal:         LONG PENDING
Balance:        102.40
Daily PnL:      +2.40
Last Trade:     WIN +6.20
==========================================
```

Stop the bot any time with **Ctrl+C** — it closes the MT5 connection cleanly.

---

## Configuration

All tunables live in **`config.py`** (one place to change anything):

```python
RISK_PERCENT = 2        # Change this to adjust risk per trade
RR_DEFAULT = 3          # Default risk:reward
RR_EXTENDED = 4         # Extended RR if liquidity target available
SESSION_START = "08:00" # NY session start EST
SESSION_END = "17:00"   # NY session end EST
NEWS_BUFFER_BEFORE = 30 # Minutes before news to stop trading
NEWS_BUFFER_AFTER = 60  # Minutes after news to resume trading
DAILY_LOSS_LIMIT = 5    # % of account, stops bot for the day
MAX_SL_POINTS = 500     # Skip trade if SL too wide
MIN_SL_POINTS = 50      # Skip trade if SL too tight
LOOP_INTERVAL = 300     # Seconds between M5 checks (5 mins)
BIAS_INTERVAL = 900     # Seconds between H1 bias rechecks (15 mins)
DEMO_MODE = True        # Switch to False for live trading
```

---

## Getting a free VPS from IC Markets

IC Markets offers a **free VPS** to clients who meet a minimum deposit/volume
requirement:

1. Log in to your IC Markets **Secure Client Area**.
2. Go to **Free Tools → VPS** (or **MetaTrader VPS**).
3. Apply for the free VPS — eligibility is usually tied to a minimum balance
   (commonly ~$5,000) or a monthly traded-volume threshold.
4. Once provisioned, connect via Remote Desktop, install MT5 + Python there, and
   run the bot so it stays online 24/5 even when your home PC is off.

---

## Deploying on a cheap Windows VPS (Contabo)

If you do not qualify for the free VPS, a low-cost Windows VPS works well:

1. Sign up at <https://contabo.com/> and order a **Cloud VPS** with a
   **Windows Server** license (the smallest tier is plenty).
2. Connect with **Remote Desktop** (`mstsc` on Windows; Microsoft Remote
   Desktop on macOS) using the IP and credentials Contabo emails you.
3. On the VPS: install the **IC Markets MT5** terminal and log in.
4. Install **Python 3.10+** and tick *Add to PATH*.
5. Copy this `xauusd_smc_bot` folder to the VPS, run
   `pip install -r requirements.txt`, create your `.env`, and start
   `python main.py`.
6. Keep the MT5 terminal and the bot running; the VPS stays online 24/7 so you
   can disconnect Remote Desktop and the bot keeps trading.

> Tip: place a shortcut to `python main.py` in the Windows **Startup** folder, or
> use Task Scheduler, so the bot relaunches automatically after a reboot.

---

## Switching from demo to live

1. Make sure you have tested thoroughly on demo.
2. In `config.py`, set:
   ```python
   DEMO_MODE = False
   ```
3. Update `.env` with your **live** account number, password, and server:
   ```ini
   MT5_SERVER=ICMarketsSC-Live
   ```
4. Log the **live** account into the MT5 terminal and restart the bot.

---

## Troubleshooting — bot is not placing trades

The bot is **conservative by design** and will sit idle most of the time. If you
expected a trade and got none, check the status block and the points below:

- **HTF bias unclear or ranging** — `HTF Bias: UNCLEAR`. No clean HH/HL or LH/LL
  structure on H1, so the bot waits.
- **No liquidity sweep detected** — `Sweep Detected: NO`. Price has not swept the
  previous session high/low against the bias within the last 8 M15 candles.
- **OB invalidated** — price already returned into the order block, so it is no
  longer a fresh zone (`OB Zone: —`).
- **News event blocking the window** — `News: BLOCKED`. Trading is paused 30 min
  before to 60 min after red USD/Gold news (or hardcoded times in safe mode).
- **Session not open** — `Session: CLOSED`. Outside 08:00–17:00 EST.
- **Daily loss limit hit** — `Signal: DAILY LOSS HALT`. The day's PnL reached
  −5%; trading resumes next NY session.

Also check `error_log.txt` for connection or order errors, and `trades_log.csv`
for the record of placed trades.

---

## Backtesting (do this BEFORE risking real money)

A month on demo is a tiny, luck-dominated sample. The backtester replays years of
history through the **exact same** `strategy.py` and `risk.py` the live bot uses,
so you get hundreds of trades and real statistics (win rate, profit factor,
drawdown) before committing capital.

### 1. Get historical M5 data

Export XAUUSD **M5** candles to a CSV with columns `time, open, high, low, close`
(a `volume` column is optional). The easiest source is your own MT5 terminal
(it's the same price history you'll trade on):

- In MT5: `View -> Symbols -> XAUUSD -> Bars`, choose **M5** and a date range,
  then export. Or use a small script with `mt5.copy_rates_range(...)` and
  `pandas.to_csv()`.

### 2. Run it

```bash
python backtest.py path/to/xauusd_m5.csv --balance 100 --data-tz UTC
```

Key flags:

| Flag | Meaning |
| --- | --- |
| `--balance` | Starting balance (default 100) |
| `--data-tz` | Timezone of your CSV's `time` column (MT5 servers are often `Etc/GMT-2`/`Etc/GMT-3`). Converted to EST so session/news filters line up. |
| `--commission` | Round-turn commission per 1.0 lot (IC Markets Raw ≈ 7) |
| `--spread-points` | Spread cost applied to entries |
| `--no-news` / `--no-session` | Disable a filter for sensitivity analysis |
| `--no-compound` | Size off the fixed starting balance instead of equity |

It prints a report and writes per-trade detail to `backtest_trades.csv`.

### How it stays honest

- **No lookahead.** At each step only candles that had *fully closed* by that
  moment are fed to the strategy; H1/M15 are derived from the M5 series.
- **Conservative fills.** Entries fill at the signal bar's close; if a later bar
  spans both SL and TP, the **stop** is assumed hit first.
- **Costs included.** Commission and spread are deducted from every trade.

### Try-before-you-buy-data sanity check

`make_synthetic_data.py` generates a fake year of M5 candles so you can see the
engine run without any data file:

```bash
python make_synthetic_data.py synthetic_xauusd_m5.csv 365
python backtest.py synthetic_xauusd_m5.csv --balance 100
```

> ⚠️ Synthetic data has **no real market edge** — it only proves the harness
> works. Judge profitability **only** on real MT5-exported history.

## Logs

- **`trades_log.csv`** — one row per trade: `date, time, direction, entry_price,
  sl, tp, rr, lot_size, result, pnl, balance_after, entry_reason`.
- **`error_log.txt`** — every exception and MT5 error, timestamped.

---

## Design notes

- All SMC detection is **rule-based and fully deterministic** — no machine
  learning, no external signals, no paid data feeds.
- MT5 provides all price data; the only external call is the ForexFactory news
  feed (with a safe-mode fallback if it fails).
- The bot runs **fully unattended** once started, auto-reconnects if MT5 drops
  (up to 3 attempts), and shuts down cleanly on Ctrl+C.

---

## Disclaimer

This software is provided for educational purposes. Automated trading is risky
and you are solely responsible for any losses. Test on demo, never risk money you
cannot afford to lose, and review the code before any live deployment.
