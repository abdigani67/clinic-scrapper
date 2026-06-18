"""
export_data.py — Pull real XAUUSD history from your IC Markets MT5 terminal.

Run this ONCE on the Windows machine where the IC Markets MT5 terminal is
installed and logged in. It connects with the same credentials as the bot (from
your .env), downloads candles, and writes a CSV that drops straight into
``compare.py`` / ``backtest.py``.

Examples
--------
    # 2 years of M5 candles (the default) -> xauusd_m5.csv
    python export_data.py

    # 3 years of M15 to a custom file
    python export_data.py --timeframe M15 --years 3 --out gold_m15.csv

After it finishes it prints the exact backtest command to run next, including
the right --data-tz for your broker server.

Note on history depth: MT5 only returns bars it has actually downloaded. If you
get fewer bars than expected, open the XAUUSD chart in MT5, set Tools ->
Options -> Charts -> "Max bars in chart" to Unlimited, scroll back on the M5
chart to force a history download, then re-run this script.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only available on Windows MT5 boxes
    mt5 = None

import config
import mt5_client as mt5c


def _timeframe(name: str):
    """Translate a timeframe label to the MT5 constant.

    Args:
        name: One of 'M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'.

    Returns:
        The MetaTrader5 timeframe constant.
    """
    table = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    if name not in table:
        raise SystemExit(f"Unknown timeframe '{name}'. Choose from {list(table)}.")
    return table[name]


def _server_tz_hint() -> str:
    """Best-effort guess of the IANA timezone string for the broker server.

    IC Markets' server clock is GMT+2 in winter and GMT+3 in summer (EET/EEST).
    The CSV's timestamps are in that server time, so the backtester needs to be
    told which zone to convert FROM. We return a sensible default; the user can
    override with --data-tz on the backtest command.

    Returns:
        str: A POSIX-style tz string (note: 'Etc/GMT-2' means UTC+2).
    """
    # 'Etc/GMT-3' == UTC+3. Etc/GMT signs are inverted on purpose (POSIX).
    return "Etc/GMT-3"


def export(timeframe: str, years: float, out: str) -> None:
    """Download candles for the configured symbol and write them to a CSV.

    Args:
        timeframe: Timeframe label, e.g. 'M5'.
        years: How many years back to fetch.
        out: Output CSV path.

    Returns:
        None.
    """
    if mt5 is None:
        raise SystemExit("MetaTrader5 is not installed. Run this on the Windows "
                         "machine with the IC Markets MT5 terminal.")

    if not mt5c.connect():
        raise SystemExit("Could not connect to MT5. Is the terminal running and "
                         "are your .env credentials correct?")

    try:
        tf = _timeframe(timeframe)
        end = datetime.now()
        start = end - timedelta(days=int(years * 365))

        print(f"Requesting {config.SYMBOL} {timeframe} from {start.date()} "
              f"to {end.date()}...")
        rates = mt5.copy_rates_range(config.SYMBOL, tf, start, end)

        # Fallback: some servers respond better to a positional bulk pull.
        if rates is None or len(rates) == 0:
            print("Range request empty — retrying with a positional bulk pull...")
            # ~ bars per year for the timeframe, capped generously.
            per_year = {"M1": 525600, "M5": 105120, "M15": 35040, "M30": 17520,
                        "H1": 8760, "H4": 2190, "D1": 365}.get(timeframe, 105120)
            count = int(per_year * years)
            rates = mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, count)

        if rates is None or len(rates) == 0:
            raise SystemExit(f"No data returned for {config.SYMBOL} {timeframe}. "
                             f"Last error: {mt5.last_error()}. See the history-depth "
                             f"note at the top of this file.")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        cols = ["time", "open", "high", "low", "close", "tick_volume"]
        df = df[[c for c in cols if c in df.columns]]
        df.to_csv(out, index=False)

        tz = _server_tz_hint()
        print(f"\n✅ Wrote {len(df):,} {timeframe} candles to {out}")
        print(f"   Range: {df['time'].iloc[0]} -> {df['time'].iloc[-1]} "
              f"(broker server time)")
        print("\nNext, rank the strategies on this REAL data:")
        print(f"   python compare.py {out} --balance 2000 --data-tz {tz}")
        print("\nOr a single full backtest of the default strategy:")
        print(f"   python backtest.py {out} --balance 2000 --data-tz {tz}")
        print(f"\n(If your IC Markets account is GBP and trades look mis-timed vs "
              f"the NY session, try --data-tz Etc/GMT-2 instead of {tz}.)")
    finally:
        mt5c.disconnect()


def main(argv=None) -> int:
    """CLI entry point for exporting MT5 history.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Export XAUUSD history from IC Markets MT5 to CSV.")
    parser.add_argument("--timeframe", default="M5",
                        help="Candle timeframe (default M5).")
    parser.add_argument("--years", type=float, default=2.0,
                        help="How many years of history to fetch (default 2).")
    parser.add_argument("--out", default="xauusd_m5.csv",
                        help="Output CSV path (default xauusd_m5.csv).")
    args = parser.parse_args(argv)
    export(args.timeframe, args.years, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
