"""
config.py — Central configuration for the XAUUSD SMC trading bot.

Every tunable parameter lives here so you only ever edit ONE file to change the
bot's behaviour. Secrets (MT5 login, password, server) are loaded from a `.env`
file via python-dotenv so they never get committed to source control.

Plain English: this is the "control panel" for the whole bot.
"""

import os

from dotenv import load_dotenv

# Load variables from a local .env file into the environment (if present).
load_dotenv()


# ----------------------------------------------------------------------------
# MT5 CONNECTION (loaded from .env — never hard-code real credentials)
# ----------------------------------------------------------------------------
# Your IC Markets MT5 account number (integer).
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
# Your MT5 account password.
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
# Broker server name. IC Markets demo/live values are provided as defaults below
# but the .env value (if any) always wins.
MT5_SERVER = os.getenv("MT5_SERVER", "")
# Optional explicit path to terminal64.exe. Leave blank to let MT5 auto-detect
# the running, logged-in terminal.
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")

# IC Markets server names — used as a convenience when MT5_SERVER is not set.
IC_MARKETS_DEMO_SERVER = "ICMarketsSC-Demo"
IC_MARKETS_LIVE_SERVER = "ICMarketsSC-Live"


# ----------------------------------------------------------------------------
# INSTRUMENT
# ----------------------------------------------------------------------------
# The only symbol this bot trades.
SYMBOL = "XAUUSD"


# ----------------------------------------------------------------------------
# RISK & REWARD
# ----------------------------------------------------------------------------
RISK_PERCENT = 2        # Change this to adjust risk per trade
RR_DEFAULT = 3          # Default risk:reward
RR_EXTENDED = 4         # Extended RR if liquidity target available


# ----------------------------------------------------------------------------
# SESSION (New York) — times are EST/America/New_York local time
# ----------------------------------------------------------------------------
SESSION_START = "08:00"  # NY session start EST
SESSION_END = "17:00"    # NY session end EST


# ----------------------------------------------------------------------------
# NEWS FILTER
# ----------------------------------------------------------------------------
NEWS_BUFFER_BEFORE = 30  # Minutes before news to stop trading
NEWS_BUFFER_AFTER = 60   # Minutes after news to resume trading


# ----------------------------------------------------------------------------
# RISK LIMITS
# ----------------------------------------------------------------------------
DAILY_LOSS_LIMIT = 5     # % of account, stops bot for the day
MAX_SL_POINTS = 500      # Skip trade if SL too wide
MIN_SL_POINTS = 50       # Skip trade if SL too tight


# ----------------------------------------------------------------------------
# LOOP TIMING
# ----------------------------------------------------------------------------
LOOP_INTERVAL = 300      # Seconds between M5 checks (5 mins)
BIAS_INTERVAL = 900      # Seconds between H1 bias rechecks (15 mins)


# ----------------------------------------------------------------------------
# MODE
# ----------------------------------------------------------------------------
DEMO_MODE = True         # Switch to False for live trading


# ----------------------------------------------------------------------------
# DERIVED / STRATEGY CONSTANTS (rarely changed)
# ----------------------------------------------------------------------------
# How many candles to pull for each timeframe analysis.
H1_CANDLES = 100         # HTF bias lookback
M15_CANDLES = 96         # Sweep / order block lookback (~1 day of M15)
M5_CANDLES = 200         # FVG lookback

# Order block / sweep detection windows.
SWEEP_LOOKBACK = 8       # Sweep must have occurred within last N M15 candles
IMPULSE_MIN_CANDLES = 3  # Minimum consecutive candles to count as an impulse

# Stop loss construction.
SL_SWING_LOOKBACK = 10   # Use the highest/lowest of last N M15 candles for SL
SL_BUFFER_POINTS = 20    # Extra buffer added beyond the swing (in points)

# Lot sizing.
MIN_LOT = 0.01           # Broker minimum
MAX_LOT = 10.00          # Hard cap we impose regardless of broker maximum
LOT_STEP = 0.01          # Lots are rounded DOWN to this step

# XAUUSD point value on IC Markets: $0.01 per point per 0.01 lot.
# Expressed per 1.00 lot that is $1.00 per point.
POINT_VALUE_PER_LOT = 1.0

# Order execution.
ORDER_DEVIATION = 20     # Slippage tolerance in points
ORDER_COMMENT = "SMC_BOT_XAUUSD"
MAGIC_NUMBER = 778899    # Identifies this bot's orders

# Reconnection.
MAX_RECONNECT_ATTEMPTS = 3

# Timezone used for all session/news logic.
TIMEZONE_EST = "America/New_York"

# Safe-mode hardcoded news times (EST) used when the live news feed fails.
SAFE_MODE_NEWS_TIMES = ["08:30", "10:00", "14:00", "14:30"]

# ForexFactory weekly calendar RSS / JSON feed.
FOREXFACTORY_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def resolve_server() -> str:
    """Return the broker server name to connect to.

    Preference order:
      1. Explicit MT5_SERVER from .env (always wins if set).
      2. IC Markets demo/live default based on DEMO_MODE.

    Returns:
        str: The server name string passed to mt5.login().
    """
    if MT5_SERVER:
        return MT5_SERVER
    return IC_MARKETS_DEMO_SERVER if DEMO_MODE else IC_MARKETS_LIVE_SERVER
