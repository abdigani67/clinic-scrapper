"""
backtest.py — Historical backtester for the XAUUSD SMC strategy.

Plain English: this replays past price data through the EXACT same strategy and
risk code the live bot uses, pretending it is trading in real time, and reports
how it would have performed (win rate, profit factor, drawdown, equity curve).

Why this matters: a month on demo gives you a tiny, luck-dominated sample. A
backtest over a year or two gives you hundreds of trades — the only honest way to
judge whether the rules have an edge BEFORE risking real money.

Design principles
-----------------
* No lookahead. At each step we only ever feed the strategy candles that had
  fully CLOSED at that moment. Higher timeframes (H1/M15) are derived from the
  single base M5 series so one data file is all you need.
* Same code path. It imports strategy.py and risk.py unchanged, so a green
  backtest means the live logic is what was tested — not a re-implementation.
* Conservative fills. Entries fill at the signal bar's close; if a later bar's
  range spans both SL and TP, we assume the STOP was hit first.

Data input
----------
A single CSV of M5 candles with columns: time, open, high, low, close, (volume).
Export from MT5: open the XAUUSD M5 chart, then in the terminal use
``File -> Save As`` on the history, or use a History Center / third-party dump.
The ``time`` column may be in any timezone — pass --data-tz to convert it to EST
so the session/news filters line up with New York.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
import risk
import strategy
from utils import EST


# ---------------------------------------------------------------------------
# Data loading & timeframe construction
# ---------------------------------------------------------------------------
def load_m5_csv(path: str, data_tz: str = "UTC") -> pd.DataFrame:
    """Load a base M5 candle CSV and return it indexed by EST timestamp.

    Args:
        path: Path to the CSV. Must contain time, open, high, low, close columns
            (case-insensitive). A volume/tick_volume column is optional.
        data_tz: Timezone the source ``time`` column is expressed in (e.g.
            'UTC', 'Etc/GMT-2' for a typical MT5 server). Converted to EST.

    Returns:
        pandas.DataFrame: Columns open, high, low, close, tick_volume indexed by
        a tz-aware EST DatetimeIndex, sorted ascending.
    """
    df = pd.read_csv(path)
    # Normalise column names.
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        raise KeyError(f"CSV missing one of columns {names}; found {list(df.columns)}")

    time_col = pick("time", "date", "datetime", "timestamp")
    out = pd.DataFrame({
        "open": df[pick("open", "o")].astype(float),
        "high": df[pick("high", "h")].astype(float),
        "low": df[pick("low", "l")].astype(float),
        "close": df[pick("close", "c")].astype(float),
    })
    try:
        out["tick_volume"] = df[pick("tick_volume", "volume", "vol", "v")].astype(float)
    except KeyError:
        out["tick_volume"] = 0.0

    ts = pd.to_datetime(df[time_col])
    # Localize to the source tz, then convert to EST.
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(data_tz)
    out.index = ts.dt.tz_convert(EST)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out


def resample(m5: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample M5 candles up to a higher timeframe with a close-time column.

    Args:
        m5: Base M5 DataFrame indexed by EST timestamp.
        rule: Pandas offset alias, e.g. '15min' or '1h'.

    Returns:
        pandas.DataFrame: Aggregated OHLC with a 'close_time' column marking when
        each candle fully completed (used for no-lookahead slicing).
    """
    agg = m5.resample(rule, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "tick_volume": "sum",
    }).dropna()
    delta = pd.Timedelta(rule)
    agg["close_time"] = agg.index + delta
    return agg


def _close_time_ns(df: pd.DataFrame) -> np.ndarray:
    """Return a sorted int64 nanosecond array of each candle's close time.

    Using integer ns lets us binary-search with np.searchsorted instead of
    scanning the whole frame every bar (O(log N) vs O(N) per lookup).

    Args:
        df: Resampled frame with a 'close_time' column.

    Returns:
        numpy.ndarray: int64 ns timestamps (UTC) of each candle's close.
    """
    # to_numpy() on a tz-aware series yields UTC-naive datetime64[ns]; the int64
    # view is ns since epoch (UTC), matching pandas Timestamp.value.
    return df["close_time"].to_numpy(dtype="datetime64[ns]").astype("int64")


def _trailing_ns(df: pd.DataFrame, close_ns: np.ndarray, now_ns: int,
                 count: int) -> pd.DataFrame:
    """Return the last ``count`` candles closed by ``now_ns`` via binary search.

    Args:
        df: The resampled frame.
        close_ns: Sorted int64 ns array from _close_time_ns(df).
        now_ns: Current bar close time in int64 ns (UTC).
        count: Number of trailing completed candles to return.

    Returns:
        pandas.DataFrame: Up to ``count`` rows, oldest first, OHLC columns only.
    """
    pos = int(np.searchsorted(close_ns, now_ns, side="right"))
    start = max(0, pos - count)
    return df.iloc[start:pos]


# ---------------------------------------------------------------------------
# Trade + result containers
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    """A single simulated trade and its outcome."""
    entry_time: pd.Timestamp
    direction: str
    entry: float
    sl: float
    tp: float
    rr: float
    lot: float
    reason: str
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    result: str | None = None      # 'WIN' | 'LOSS'
    pnl: float = 0.0
    balance_after: float = 0.0


@dataclass
class BacktestResult:
    """Aggregated backtest output."""
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)  # (time, balance)
    starting_balance: float = 0.0
    ending_balance: float = 0.0


# ---------------------------------------------------------------------------
# Filters reused from the live bot's semantics
# ---------------------------------------------------------------------------
def _session_open_est(ts: pd.Timestamp) -> bool:
    """Return whether an EST timestamp is inside the NY session window."""
    start_h, start_m = (int(x) for x in config.SESSION_START.split(":"))
    end_h, end_m = (int(x) for x in config.SESSION_END.split(":"))
    minutes = ts.hour * 60 + ts.minute
    return (start_h * 60 + start_m) <= minutes <= (end_h * 60 + end_m)


def _past_entry_cutoff(ts: pd.Timestamp) -> bool:
    """Return whether ``ts`` is too close to the session end to open a trade.

    No new intraday trade should be opened in the final
    config.NO_ENTRY_BEFORE_CLOSE_MIN minutes (it cannot play out before the
    forced end-of-day close).
    """
    end_h, end_m = (int(x) for x in config.SESSION_END.split(":"))
    minutes = ts.hour * 60 + ts.minute
    return minutes > (end_h * 60 + end_m) - config.NO_ENTRY_BEFORE_CLOSE_MIN


def _at_or_past_session_end(ts: pd.Timestamp) -> bool:
    """Return whether ``ts`` is at or beyond the NY session close."""
    end_h, end_m = (int(x) for x in config.SESSION_END.split(":"))
    return (ts.hour * 60 + ts.minute) >= (end_h * 60 + end_m)


def _safe_news_block(ts: pd.Timestamp) -> bool:
    """Return whether an EST timestamp falls in a hardcoded safe-mode news window.

    Uses config.SAFE_MODE_NEWS_TIMES with the same before/after buffers as the
    live bot. This is a deterministic proxy for the live ForexFactory feed, which
    cannot be replayed historically.
    """
    minutes = ts.hour * 60 + ts.minute
    for hhmm in config.SAFE_MODE_NEWS_TIMES:
        h, m = (int(x) for x in hhmm.split(":"))
        event = h * 60 + m
        if (event - config.NEWS_BUFFER_BEFORE) <= minutes <= (event + config.NEWS_BUFFER_AFTER):
            return True
    return False


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
def run_backtest(
    m5: pd.DataFrame,
    starting_balance: float = 100.0,
    point: float = 0.01,
    commission_per_lot: float = 7.0,
    spread_points: float = 10.0,
    apply_session: bool = True,
    apply_news: bool = True,
    compound: bool = True,
    warmup: int = 300,
    progress: bool = True,
) -> BacktestResult:
    """Replay the strategy over historical M5 data and simulate trades.

    Args:
        m5: M5 DataFrame indexed by EST timestamp (from load_m5_csv).
        starting_balance: Account balance to start with (account currency).
        point: Instrument point size (XAUUSD = 0.01).
        commission_per_lot: Round-turn commission in account currency per 1.0
            lot (IC Markets Raw ≈ $7). Charged proportionally to lot size.
        spread_points: Spread cost in points applied to the entry (gold raw
            spread is small; default 10 points ≈ $0.10/0.01 lot).
        apply_session: Enforce the NY session filter.
        apply_news: Enforce the safe-mode hardcoded news windows.
        compound: If True, size off the live (growing/shrinking) balance.
        warmup: Number of initial M5 bars to skip so higher TFs have history.
        progress: Print a progress line periodically.

    Returns:
        BacktestResult: Trades, equity curve, and start/end balances.
    """
    h1 = resample(m5, "1h")
    m15 = resample(m5, "15min")
    # Pre-compute sorted close-time arrays for fast binary-search slicing.
    h1_ns = _close_time_ns(h1)
    m15_ns = _close_time_ns(m15)
    h1_ohlc = h1[["open", "high", "low", "close", "tick_volume"]]
    m15_ohlc = m15[["open", "high", "low", "close", "tick_volume"]]

    balance = starting_balance
    day_open_balance = balance
    current_day = None
    daily_halt = False

    open_trade: Trade | None = None
    result = BacktestResult(starting_balance=starting_balance)

    index = m5.index
    n = len(m5)

    for i in range(warmup, n):
        bar = m5.iloc[i]
        ts = index[i]
        now_ns = (ts.value + pd.Timedelta("5min").value)

        # --- Roll the trading day (reset daily loss halt) -----------------
        day = ts.date()
        if day != current_day:
            current_day = day
            day_open_balance = balance
            daily_halt = False

        # --- Manage an open trade first (check this bar's range) ----------
        if open_trade is not None:
            hit = _check_exit(open_trade, bar)
            if hit is not None:
                exit_price, res = hit
                pnl = _pnl(open_trade, exit_price, point, commission_per_lot)
                balance += pnl
                open_trade.exit_time = ts
                open_trade.exit = exit_price
                open_trade.result = res
                open_trade.pnl = pnl
                open_trade.balance_after = balance
                result.trades.append(open_trade)
                result.equity_curve.append((ts, balance))
                open_trade = None
            else:
                # Still open — nothing else to do this bar.
                continue

        # --- Entry filters ------------------------------------------------
        if apply_session and not _session_open_est(ts):
            continue
        if apply_news and _safe_news_block(ts):
            continue
        if daily_halt:
            continue
        # Daily loss limit on realised PnL within the day.
        if risk.daily_loss_hit(day_open_balance, balance - day_open_balance, 0.0):
            daily_halt = True
            continue

        # --- Build no-lookahead windows -----------------------------------
        # H1/M15 sliced by binary search on close time; M5 uses the loop index
        # directly (candle i has just closed, so i-count+1..i are completed).
        h1_win = _trailing_ns(h1_ohlc, h1_ns, now_ns, config.H1_CANDLES)
        m15_win = _trailing_ns(m15_ohlc, m15_ns, now_ns, config.M15_CANDLES)
        m5_win = m5.iloc[max(0, i - config.M5_CANDLES + 1):i + 1]
        if len(h1_win) < 20 or len(m15_win) < 20 or len(m5_win) < 5:
            continue

        price = float(bar["close"])
        sig = strategy.signal(h1_win, m15_win, m5_win, price)
        if sig["direction"] is None:
            continue

        direction = sig["direction"]
        # Apply spread to the entry (buy a touch higher, sell a touch lower).
        entry = price + spread_points * point * (1 if direction == "BUY" else -1)

        sl = risk.stop_loss(direction, entry, m15_win, point)
        if sl is None:
            continue
        tp, rr = risk.take_profit(direction, entry, sl, m15_win, point)

        sizing_balance = balance if compound else starting_balance
        lot = risk.position_size(sizing_balance, entry, sl, point)
        if lot <= 0:
            continue

        open_trade = Trade(
            entry_time=ts, direction=direction, entry=entry, sl=sl, tp=tp,
            rr=rr, lot=lot, reason=sig["reason"],
        )

        if progress and i % 5000 == 0:
            print(f"  ...bar {i}/{n}  {ts.date()}  balance={balance:.2f}  "
                  f"trades={len(result.trades)}", file=sys.stderr)

    result.ending_balance = balance
    return result


def run_with_signals(
    m5: pd.DataFrame,
    signals: pd.Series,
    starting_balance: float = 100.0,
    point: float = 0.01,
    commission_per_lot: float = 7.0,
    spread_points: float = 10.0,
    apply_session: bool = True,
    apply_news: bool = True,
    compound: bool = True,
    warmup: int = 300,
) -> BacktestResult:
    """Backtest a precomputed +1/-1/0 signal series through the SAME risk engine.

    Identical trade management, SL/TP, sizing, session and news filters as
    run_backtest — only the entry direction comes from ``signals`` instead of
    the SMC strategy. This is how alternative strategies are compared on a level
    playing field.

    Args:
        m5: M5 DataFrame indexed by EST timestamp.
        signals: Series aligned to m5.index with values in {1, -1, 0}.
        starting_balance: Account balance to start with.
        point: Instrument point size.
        commission_per_lot: Round-turn commission per 1.0 lot.
        spread_points: Spread cost in points applied to entries.
        apply_session: Enforce the NY session filter.
        apply_news: Enforce the safe-mode news windows.
        compound: Size off live balance if True.
        warmup: Initial bars to skip for indicator history.

    Returns:
        BacktestResult: Trades, equity curve, balances.
    """
    m15 = resample(m5, "15min")
    m15_ns = _close_time_ns(m15)
    m15_ohlc = m15[["open", "high", "low", "close", "tick_volume"]]

    balance = starting_balance
    day_open_balance = balance
    current_day = None
    daily_halt = False
    open_trade: Trade | None = None
    result = BacktestResult(starting_balance=starting_balance)

    index = m5.index
    sig_vals = signals.to_numpy()
    n = len(m5)

    for i in range(warmup, n):
        bar = m5.iloc[i]
        ts = index[i]
        now_ns = ts.value + pd.Timedelta("5min").value

        day = ts.date()
        if day != current_day:
            current_day = day
            day_open_balance = balance
            daily_halt = False

        if open_trade is not None:
            hit = _check_exit(open_trade, bar)
            # Intraday: force-close any trade still open at the session end.
            if hit is None and config.INTRADAY_EXIT and _at_or_past_session_end(ts):
                hit = (float(bar["close"]), "EOD")
            if hit is not None:
                exit_price, res = hit
                pnl = _pnl(open_trade, exit_price, point, commission_per_lot)
                balance += pnl
                open_trade.exit_time = ts
                open_trade.exit = exit_price
                open_trade.result = "WIN" if pnl > 0 else "LOSS"
                open_trade.pnl = pnl
                open_trade.balance_after = balance
                result.trades.append(open_trade)
                result.equity_curve.append((ts, balance))
                open_trade = None
            else:
                continue

        direction_val = sig_vals[i]
        if direction_val == 0:
            continue
        if apply_session and not _session_open_est(ts):
            continue
        # Intraday: no new entries in the final minutes before the close.
        if config.INTRADAY_EXIT and _past_entry_cutoff(ts):
            continue
        if apply_news and _safe_news_block(ts):
            continue
        if daily_halt:
            continue
        if risk.daily_loss_hit(day_open_balance, balance - day_open_balance, 0.0):
            daily_halt = True
            continue

        direction = "BUY" if direction_val > 0 else "SELL"
        m15_win = _trailing_ns(m15_ohlc, m15_ns, now_ns, config.M15_CANDLES)
        if len(m15_win) < max(config.SL_SWING_LOOKBACK, config.ATR_PERIOD + 1):
            continue

        price = float(bar["close"])
        entry = price + spread_points * point * (1 if direction == "BUY" else -1)
        sl = risk.compute_stop(direction, entry, m15_win, point)
        if sl is None:
            continue
        tp, rr = risk.take_profit(direction, entry, sl, m15_win, point)
        sizing_balance = balance if compound else starting_balance
        lot = risk.position_size(sizing_balance, entry, sl, point)
        if lot <= 0:
            continue

        open_trade = Trade(
            entry_time=ts, direction=direction, entry=entry, sl=sl, tp=tp,
            rr=rr, lot=lot, reason=f"signal={direction}",
        )

    result.ending_balance = balance
    return result


def _check_exit(trade: Trade, bar) -> tuple | None:
    """Determine whether a bar's range hit the trade's SL or TP.

    Conservative rule: if the bar spans BOTH levels, assume the STOP was hit
    first (worst case for us).

    Args:
        trade: The open trade.
        bar: The current M5 candle row (has high/low).

    Returns:
        tuple(float, str) | None: (exit_price, 'WIN'|'LOSS') if closed, else None.
    """
    high, low = float(bar["high"]), float(bar["low"])
    if trade.direction == "BUY":
        hit_sl = low <= trade.sl
        hit_tp = high >= trade.tp
        if hit_sl and hit_tp:
            return trade.sl, "LOSS"
        if hit_sl:
            return trade.sl, "LOSS"
        if hit_tp:
            return trade.tp, "WIN"
    else:  # SELL
        hit_sl = high >= trade.sl
        hit_tp = low <= trade.tp
        if hit_sl and hit_tp:
            return trade.sl, "LOSS"
        if hit_sl:
            return trade.sl, "LOSS"
        if hit_tp:
            return trade.tp, "WIN"
    return None


def _pnl(trade: Trade, exit_price: float, point: float,
         commission_per_lot: float) -> float:
    """Compute the account-currency PnL of a closed trade, net of commission.

    Args:
        trade: The trade (entry, direction, lot).
        exit_price: Fill price at exit.
        point: Instrument point size.
        commission_per_lot: Round-turn commission per 1.0 lot.

    Returns:
        float: Net profit/loss in account currency.
    """
    move_points = (exit_price - trade.entry) / point
    if trade.direction == "SELL":
        move_points = -move_points
    gross = move_points * trade.lot * config.POINT_VALUE_PER_LOT
    commission = commission_per_lot * trade.lot
    return gross - commission


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def compute_stats(result: BacktestResult) -> dict:
    """Compute summary performance statistics from a backtest result.

    Args:
        result: The BacktestResult from run_backtest.

    Returns:
        dict: Headline metrics (trade count, win rate, profit factor, expectancy,
        max drawdown %, return %, etc.).
    """
    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"trades": 0}

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    total_pnl = sum(t.pnl for t in trades)

    # Max drawdown on the equity curve.
    balances = [result.starting_balance] + [b for _, b in result.equity_curve]
    peak = balances[0]
    max_dd = 0.0
    for b in balances:
        peak = max(peak, b)
        dd = (peak - b) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n * 100,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "expectancy": total_pnl / n,
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (gross_loss / len(losses)) if losses else 0.0,
        "total_pnl": total_pnl,
        "return_pct": total_pnl / result.starting_balance * 100,
        "max_drawdown_pct": max_dd * 100,
        "ending_balance": result.ending_balance,
    }


def print_report(result: BacktestResult, stats: dict) -> None:
    """Pretty-print the backtest report to stdout.

    Args:
        result: The BacktestResult.
        stats: Output of compute_stats.

    Returns:
        None.
    """
    line = "=" * 50
    print(line)
    print("XAUUSD SMC BOT — BACKTEST REPORT")
    print(line)
    if stats.get("trades", 0) == 0:
        print("No trades were generated over this data set.")
        print(line)
        return
    print(f"Starting balance:   {result.starting_balance:,.2f}")
    print(f"Ending balance:     {stats['ending_balance']:,.2f}")
    print(f"Net P/L:            {stats['total_pnl']:+,.2f}  "
          f"({stats['return_pct']:+.1f}%)")
    print(f"Total trades:       {stats['trades']}")
    print(f"Wins / Losses:      {stats['wins']} / {stats['losses']}")
    print(f"Win rate:           {stats['win_rate']:.1f}%")
    pf = stats["profit_factor"]
    print(f"Profit factor:      {'∞' if pf == float('inf') else f'{pf:.2f}'}")
    print(f"Expectancy/trade:   {stats['expectancy']:+,.2f}")
    print(f"Avg win / loss:     {stats['avg_win']:,.2f} / {stats['avg_loss']:,.2f}")
    print(f"Max drawdown:       {stats['max_drawdown_pct']:.1f}%")
    print(line)


def save_trades_csv(result: BacktestResult, path: str) -> None:
    """Write all simulated trades to a CSV for inspection.

    Args:
        result: The BacktestResult.
        path: Output CSV path.

    Returns:
        None.
    """
    rows = []
    for t in result.trades:
        rows.append({
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "direction": t.direction,
            "entry": round(t.entry, 2),
            "sl": round(t.sl, 2),
            "tp": round(t.tp, 2),
            "rr": t.rr,
            "lot": t.lot,
            "result": t.result,
            "pnl": round(t.pnl, 2),
            "balance_after": round(t.balance_after, 2),
            "reason": t.reason,
        })
    pd.DataFrame(rows).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    """Command-line entry point for running a backtest from a CSV file.

    Returns:
        int: Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description="Backtest the XAUUSD SMC strategy.")
    parser.add_argument("csv", help="Path to M5 candle CSV (time,open,high,low,close).")
    parser.add_argument("--balance", type=float, default=100.0,
                        help="Starting balance (default 100).")
    parser.add_argument("--data-tz", default="UTC",
                        help="Timezone of the CSV time column (default UTC).")
    parser.add_argument("--commission", type=float, default=7.0,
                        help="Round-turn commission per 1.0 lot (default 7).")
    parser.add_argument("--spread-points", type=float, default=10.0,
                        help="Spread cost in points applied to entries.")
    parser.add_argument("--no-session", action="store_true",
                        help="Disable the NY session filter.")
    parser.add_argument("--no-news", action="store_true",
                        help="Disable the safe-mode news filter.")
    parser.add_argument("--no-compound", action="store_true",
                        help="Size off the fixed starting balance, not equity.")
    parser.add_argument("--out", default="backtest_trades.csv",
                        help="Where to write the per-trade CSV.")
    args = parser.parse_args(argv)

    print(f"Loading {args.csv} (tz={args.data_tz})...")
    m5 = load_m5_csv(args.csv, args.data_tz)
    print(f"Loaded {len(m5):,} M5 candles "
          f"({m5.index[0]} -> {m5.index[-1]}).")

    result = run_backtest(
        m5,
        starting_balance=args.balance,
        commission_per_lot=args.commission,
        spread_points=args.spread_points,
        apply_session=not args.no_session,
        apply_news=not args.no_news,
        compound=not args.no_compound,
    )
    stats = compute_stats(result)
    print_report(result, stats)
    if result.trades:
        save_trades_csv(result, args.out)
        print(f"Per-trade detail written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
