"""
utils.py — Logging helpers, time helpers, and the console status printer.

Plain English: shared "plumbing" used by every other module — writing trades to
a CSV, writing errors to a text log, telling the time in New York, and printing
the pretty status block you see in the terminal.
"""

import csv
import os
from datetime import datetime

import pytz

import config

# File paths (kept alongside the bot so logs are easy to find).
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_LOG = os.path.join(_BASE_DIR, "trades_log.csv")
ERROR_LOG = os.path.join(_BASE_DIR, "error_log.txt")

# Columns for the trade journal, in order.
TRADE_LOG_COLUMNS = [
    "date",
    "time",
    "direction",
    "entry_price",
    "sl",
    "tp",
    "rr",
    "lot_size",
    "result",
    "pnl",
    "balance_after",
    "entry_reason",
]

# Single shared timezone object for New York / EST.
EST = pytz.timezone(config.TIMEZONE_EST)


def now_est() -> datetime:
    """Return the current time as a timezone-aware datetime in New York time.

    Returns:
        datetime: Current moment localized to America/New_York.
    """
    return datetime.now(EST)


def fmt_est(dt: datetime | None = None) -> str:
    """Format a datetime as a friendly EST clock string, e.g. ``09:45am``.

    Args:
        dt: Datetime to format. Defaults to the current EST time.

    Returns:
        str: Lower-case 12-hour clock string with am/pm suffix.
    """
    if dt is None:
        dt = now_est()
    return dt.strftime("%I:%M%p").lstrip("0").lower()


def session_open(check_time: datetime | None = None) -> bool:
    """Return whether the New York trading session is currently open.

    The window is config.SESSION_START to config.SESSION_END in EST. The bot
    only trades inside this window.

    Args:
        check_time: EST datetime to test. Defaults to the current EST time.

    Returns:
        bool: True if within the NY session window.
    """
    if check_time is None:
        check_time = now_est()
    start_h, start_m = (int(x) for x in config.SESSION_START.split(":"))
    end_h, end_m = (int(x) for x in config.SESSION_END.split(":"))
    start = check_time.replace(hour=start_h, minute=start_m, second=0,
                               microsecond=0)
    end = check_time.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return start <= check_time <= end


def log_error(message: str) -> None:
    """Append an error/exception message to error_log.txt with a timestamp.

    Args:
        message: Human-readable description of the error.

    Returns:
        None.
    """
    stamp = now_est().strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{stamp}] {message}\n"
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        # If we cannot even write the error log, fall back to stderr-ish print.
        print(f"ERROR (could not write error_log.txt): {line}", end="")
    # Always echo errors to the console too so they are visible while running.
    print(f"⚠️  {message}")


def log_trade(row: dict) -> None:
    """Append a completed (or opened) trade to trades_log.csv.

    Creates the file with a header row if it does not yet exist.

    Args:
        row: Mapping of column name -> value. Missing columns are written blank.

    Returns:
        None.
    """
    file_exists = os.path.isfile(TRADES_LOG)
    try:
        with open(TRADES_LOG, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_LOG_COLUMNS)
            if not file_exists:
                writer.writeheader()
            # Only keep known columns; fill missing ones with "".
            clean = {col: row.get(col, "") for col in TRADE_LOG_COLUMNS}
            writer.writerow(clean)
    except OSError as exc:
        log_error(f"Failed to write trade log: {exc}")


def print_status(status: dict) -> None:
    """Print the formatted console status block.

    Args:
        status: Mapping with keys: time_est, session, news, bias, sweep,
            ob_zone, fvg, signal, balance, daily_pnl, last_trade. Any missing
            key is rendered as a sensible placeholder.

    Returns:
        None.
    """
    line = "=========================================="
    print(line)
    print("XAUUSD SMC BOT — IC Markets MT5")
    print(f"Time (EST):     {status.get('time_est', fmt_est())}")
    print(f"Session:        {status.get('session', 'CLOSED')}")
    print(f"News:           {status.get('news', 'CLEAR')}")
    print(f"HTF Bias:       {status.get('bias', 'UNCLEAR')}")
    print(f"Sweep Detected: {status.get('sweep', 'NO')}")
    print(f"OB Zone:        {status.get('ob_zone', '—')}")
    print(f"FVG Active:     {status.get('fvg', 'NO')}")
    print(f"Signal:         {status.get('signal', 'NONE')}")
    print(f"Balance:        {status.get('balance', '—')}")
    print(f"Daily PnL:      {status.get('daily_pnl', '—')}")
    print(f"Last Trade:     {status.get('last_trade', '—')}")
    print(line)
