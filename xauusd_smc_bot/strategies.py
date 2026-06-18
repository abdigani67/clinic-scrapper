"""
strategies.py — A library of candidate entry strategies to compare.

Every strategy here answers ONE question: "in which direction, if any, should we
enter on this bar?" It returns only a direction. The stop-loss, take-profit,
position sizing, daily-loss limit and NY-session filter are all handled by the
unchanged risk.py / session logic — so swapping strategies never changes your
risk management.

Two interfaces are provided for each strategy:

  * a VECTORISED signal builder (``signals_*``) used by the backtest comparison
    — it computes a lookahead-safe +1/-1/0 direction for every M5 bar at once;
  * a LIVE function (``live_*``) used by the running bot — same logic on the
    trailing window of candles.

All indicators are computed only from candles that had CLOSED at decision time,
so there is no lookahead bias.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Indicator helpers (pure pandas — no extra dependencies)
# ---------------------------------------------------------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Mapping M15 events onto the M5 timeline (lookahead-safe)
# ---------------------------------------------------------------------------
def _map_m15_events_to_m5(m15: pd.DataFrame, events: pd.Series,
                          m5_index: pd.DatetimeIndex) -> pd.Series:
    """Place each M15 event on the M5 bar that closes when the M15 bar closes.

    An M15 candle's signal only becomes known when it closes (open + 15min).
    Because the 15-minute grid aligns with the 5-minute grid, that close instant
    is exactly one M5 bar's close — so we attach the event there and nowhere
    else (no forward-fill, so a signal fires once, not for 3 bars).

    Args:
        m15: M15 frame (its index is candle OPEN time, EST).
        events: Series aligned to m15.index with values in {1, -1, 0}.
        m5_index: The M5 DatetimeIndex to project onto.

    Returns:
        pandas.Series: +1/-1/0 per M5 bar, indexed by m5_index.
    """
    close_time = m15.index + pd.Timedelta("15min")
    ev = pd.Series(np.asarray(events, dtype="float64"), index=close_time)
    ev = ev[~ev.index.duplicated(keep="first")]
    decision_time = m5_index + pd.Timedelta("5min")
    mapped = ev.reindex(decision_time).fillna(0.0)
    mapped.index = m5_index
    return mapped


# ---------------------------------------------------------------------------
# Strategy 1 — EMA trend crossover (classic trend following)
# ---------------------------------------------------------------------------
def signals_ema_cross(m5, m15, h1, fast: int = 21, slow: int = 55) -> pd.Series:
    """Trend-following: go with the trend when a fast EMA crosses a slow EMA.

    Concept: when the fast EMA crosses ABOVE the slow EMA the short-term trend
    has turned up (buy); a cross below turns it down (sell). One signal per
    cross. This is the canonical, heavily-researched trend-following entry.

    Returns:
        pandas.Series: +1/-1/0 direction per M5 bar.
    """
    ef = ema(m15["close"], fast)
    es = ema(m15["close"], slow)
    trend = np.sign(ef - es)
    cross = trend.diff()
    events = pd.Series(0.0, index=m15.index)
    events[cross > 0] = 1.0
    events[cross < 0] = -1.0
    return _map_m15_events_to_m5(m15, events, m5.index)


# ---------------------------------------------------------------------------
# Strategy 2 — Donchian channel breakout (Turtle-style)
# ---------------------------------------------------------------------------
def signals_donchian(m5, m15, h1, lookback: int = 20) -> pd.Series:
    """Breakout: buy a new N-bar high, sell a new N-bar low.

    Concept: price closing beyond the highest high / lowest low of the prior N
    candles signals a breakout that often continues. This is the core Turtle
    Traders entry and one of the most robust real-world momentum rules.

    Returns:
        pandas.Series: +1/-1/0 direction per M5 bar.
    """
    hh = m15["high"].rolling(lookback).max().shift(1)
    ll = m15["low"].rolling(lookback).min().shift(1)
    break_up = m15["close"] > hh
    break_dn = m15["close"] < ll
    # Fire only on the candle that first breaks (rising edge), not every bar.
    fresh_up = break_up & ~break_up.shift(1).fillna(False)
    fresh_dn = break_dn & ~break_dn.shift(1).fillna(False)
    events = pd.Series(0.0, index=m15.index)
    events[fresh_up] = 1.0
    events[fresh_dn] = -1.0
    return _map_m15_events_to_m5(m15, events, m5.index)


# ---------------------------------------------------------------------------
# Strategy 3 — Trend-filtered momentum pullback (EMA200 + RSI)
# ---------------------------------------------------------------------------
def signals_pullback(m5, m15, h1, trend_span: int = 200,
                     rsi_buy: float = 40, rsi_sell: float = 60) -> pd.Series:
    """Buy dips in an uptrend, sell rallies in a downtrend.

    Concept: use a long EMA as the trend filter (price above EMA200 = uptrend).
    Within an uptrend, an RSI dip below 40 is a pullback to buy; within a
    downtrend, an RSI pop above 60 is a rally to sell. Enters with the trend at
    a better price than a raw breakout.

    Returns:
        pandas.Series: +1/-1/0 direction per M5 bar.
    """
    trend_ema = ema(m15["close"], trend_span)
    r = rsi(m15["close"], 14)
    up = m15["close"] > trend_ema
    dn = m15["close"] < trend_ema
    buy = up & (r < rsi_buy) & (r.shift(1) >= rsi_buy)
    sell = dn & (r > rsi_sell) & (r.shift(1) <= rsi_sell)
    events = pd.Series(0.0, index=m15.index)
    events[buy] = 1.0
    events[sell] = -1.0
    return _map_m15_events_to_m5(m15, events, m5.index)


# ---------------------------------------------------------------------------
# Strategy 4 — Opening Range Breakout (anchored to the NY session)
# ---------------------------------------------------------------------------
def signals_orb(m5, m15, h1, range_minutes: int = 60) -> pd.Series:
    """Break of the first hour's range after the NY open.

    Concept: the high/low of the first ``range_minutes`` after 08:00 EST defines
    the day's opening range. The first close beyond it (in either direction)
    signals the day's directional move. One trade per day. Dovetails naturally
    with the NY-session filter you wanted kept.

    Returns:
        pandas.Series: +1/-1/0 direction per M5 bar.
    """
    idx = m5.index
    minutes = idx.hour * 60 + idx.minute
    open_start = 8 * 60
    open_end = open_start + range_minutes
    in_range = (minutes >= open_start) & (minutes < open_end)
    after_range = minutes >= open_end

    df = pd.DataFrame({
        "high": m5["high"].values,
        "low": m5["low"].values,
        "close": m5["close"].values,
        "in_range": in_range,
        "after": after_range,
        "day": idx.date,
    }, index=idx)

    sig = pd.Series(0.0, index=idx)
    for _, day_df in df.groupby("day"):
        rng = day_df[day_df["in_range"]]
        if rng.empty:
            continue
        hi = rng["high"].max()
        lo = rng["low"].min()
        post = day_df[day_df["after"]]
        if post.empty:
            continue
        broke_up = post["close"] > hi
        broke_dn = post["close"] < lo
        # First breakout of the day only.
        first_up = broke_up.idxmax() if broke_up.any() else None
        first_dn = broke_dn.idxmax() if broke_dn.any() else None
        if first_up is not None and (first_dn is None or first_up <= first_dn):
            sig.loc[first_up] = 1.0
        elif first_dn is not None:
            sig.loc[first_dn] = -1.0
    return sig


# ---------------------------------------------------------------------------
# Strategy 5 — Bollinger mean reversion (CONTROL / counter-trend)
# ---------------------------------------------------------------------------
def signals_bollinger(m5, m15, h1, period: int = 20, k: float = 2.0) -> pd.Series:
    """Fade extremes: buy the lower band, sell the upper band.

    Concept: price poking outside a Bollinger band is "stretched" and often
    snaps back. Included as a counter-trend CONTROL — on trending data it should
    UNDER-perform the trend strategies, which is a useful sanity check that the
    comparison is meaningful.

    Returns:
        pandas.Series: +1/-1/0 direction per M5 bar.
    """
    ma = m15["close"].rolling(period).mean()
    sd = m15["close"].rolling(period).std()
    lower = ma - k * sd
    upper = ma + k * sd
    buy = (m15["close"] < lower) & (m15["close"].shift(1) >= lower.shift(1))
    sell = (m15["close"] > upper) & (m15["close"].shift(1) <= upper.shift(1))
    events = pd.Series(0.0, index=m15.index)
    events[buy] = 1.0
    events[sell] = -1.0
    return _map_m15_events_to_m5(m15, events, m5.index)


# Registry used by the comparison runner and the live bot.
STRATEGIES = {
    "ema_cross": signals_ema_cross,
    "donchian": signals_donchian,
    "pullback": signals_pullback,
    "orb": signals_orb,
    "bollinger": signals_bollinger,
}


# ---------------------------------------------------------------------------
# LIVE interface — direction from the trailing window (used by the running bot)
# ---------------------------------------------------------------------------
def live_direction(name: str, h1: pd.DataFrame, m15: pd.DataFrame,
                   m5: pd.DataFrame) -> str | None:
    """Return 'BUY'/'SELL'/None for the most recent bar under strategy ``name``.

    Recomputes the chosen strategy's signal on the supplied trailing windows and
    returns the action for the latest M5 bar. Used by main.py in live trading so
    the live decision matches the backtested logic exactly.

    Args:
        name: Strategy key from STRATEGIES.
        h1, m15, m5: Trailing candle windows (most recent last).

    Returns:
        str | None: 'BUY', 'SELL', or None.
    """
    func = STRATEGIES[name]
    sig = func(m5, m15, h1)
    if len(sig) == 0:
        return None
    val = float(sig.iloc[-1])
    if val > 0:
        return "BUY"
    if val < 0:
        return "SELL"
    return None
