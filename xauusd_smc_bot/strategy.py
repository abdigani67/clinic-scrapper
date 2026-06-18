"""
strategy.py — All Smart Money Concepts (SMC) detection logic.

Plain English overview of the "top-down" approach this bot uses:

  1. BIAS (H1)  — What direction is the big-picture trend? We only trade WITH it.
  2. SWEEP (M15)— Did price grab liquidity by spiking past a recent high/low and
                  snapping back? Smart money often does this before reversing.
  3. ORDER BLOCK (M15) — The last opposite candle before a strong move. Price
                  often returns to this "institutional footprint" before
                  continuing.
  4. FVG (M5)   — A Fair Value Gap is a price imbalance (a 3-candle gap) that the
                  market tends to revisit. We use it as a precise entry trigger.
  5. SIGNAL     — When all of the above line up and price is inside the FVG, we
                  have a high-probability entry.

Every detection function is rule-based and fully deterministic: same candles in,
same answer out. No machine learning, no external signals.
"""

import numpy as np
import pandas as pd

import config


# ---------------------------------------------------------------------------
# 1. HTF BIAS (1H)
# ---------------------------------------------------------------------------
def _swing_points(df: pd.DataFrame, left: int = 2, right: int = 2) -> tuple:
    """Identify swing-high and swing-low indices in a candle DataFrame.

    A swing high is a candle whose high is greater than the highs of ``left``
    candles before and ``right`` candles after it; a swing low is the mirror.

    Args:
        df: Candle DataFrame with 'high' and 'low' columns.
        left: Candles required on the left to confirm a swing.
        right: Candles required on the right to confirm a swing.

    Returns:
        tuple(list[int], list[int]): (swing_high_indices, swing_low_indices).
    """
    highs, lows = [], []
    n = len(df)
    for i in range(left, n - right):
        window_high = df["high"].iloc[i - left:i + right + 1]
        window_low = df["low"].iloc[i - left:i + right + 1]
        if df["high"].iloc[i] == window_high.max() and \
                (window_high == df["high"].iloc[i]).sum() == 1:
            highs.append(i)
        if df["low"].iloc[i] == window_low.min() and \
                (window_low == df["low"].iloc[i]).sum() == 1:
            lows.append(i)
    return highs, lows


def bias(h1: pd.DataFrame) -> str:
    """Determine higher-timeframe bias from H1 swing structure.

    Concept: A bullish market makes Higher Highs (HH) and Higher Lows (HL). A
    bearish market makes Lower Highs (LH) and Lower Lows (LL). We look at the two
    most recent swing highs and swing lows to classify the structure.

    Args:
        h1: H1 candle DataFrame (most recent last).

    Returns:
        str: 'BULLISH', 'BEARISH', or 'UNCLEAR' (range / not enough structure).
    """
    if h1 is None or len(h1) < 10:
        return "UNCLEAR"

    highs, lows = _swing_points(h1)
    if len(highs) < 2 or len(lows) < 2:
        return "UNCLEAR"

    last_two_highs = [h1["high"].iloc[i] for i in highs[-2:]]
    last_two_lows = [h1["low"].iloc[i] for i in lows[-2:]]

    higher_high = last_two_highs[-1] > last_two_highs[-2]
    higher_low = last_two_lows[-1] > last_two_lows[-2]
    lower_high = last_two_highs[-1] < last_two_highs[-2]
    lower_low = last_two_lows[-1] < last_two_lows[-2]

    if higher_high and higher_low:
        return "BULLISH"
    if lower_high and lower_low:
        return "BEARISH"
    return "UNCLEAR"


# ---------------------------------------------------------------------------
# 2. LIQUIDITY SWEEP (15M)
# ---------------------------------------------------------------------------
def _prev_session_high_low(m15: pd.DataFrame) -> tuple:
    """Estimate the previous New York session high and low from M15 data.

    We approximate "previous session" as the older half of the supplied window,
    which (with the default 96 M15 candles ≈ 24h) captures the prior day's
    range. This gives the liquidity levels that price may sweep.

    Args:
        m15: M15 candle DataFrame.

    Returns:
        tuple(float, float): (previous_session_high, previous_session_low).
    """
    half = len(m15) // 2
    prev = m15.iloc[:half] if half > 0 else m15
    return float(prev["high"].max()), float(prev["low"].min())


def sweep(m15: pd.DataFrame, htf_bias: str) -> dict:
    """Detect a recent liquidity sweep against the HTF bias.

    Concept: Before a real move, price often spikes *past* a known high or low to
    trigger stop-losses (grab liquidity), then closes back inside the range. In a
    BULLISH market we want a sweep of the LOWS (a fake breakdown); in a BEARISH
    market we want a sweep of the HIGHS (a fake breakout).

    The sweep must have occurred within the last ``SWEEP_LOOKBACK`` candles.

    Args:
        m15: M15 candle DataFrame.
        htf_bias: 'BULLISH' or 'BEARISH'.

    Returns:
        dict: {'detected': bool, 'type': 'LOW'|'HIGH'|None, 'level': float|None,
               'index': int|None}.
    """
    result = {"detected": False, "type": None, "level": None, "index": None}
    if m15 is None or len(m15) < config.M15_CANDLES // 2:
        return result

    prev_high, prev_low = _prev_session_high_low(m15)
    start = max(0, len(m15) - config.SWEEP_LOOKBACK)

    for i in range(start, len(m15)):
        candle = m15.iloc[i]
        if htf_bias == "BULLISH":
            # Sweep of the lows: wick pierces below prev_low, close back above.
            if candle["low"] < prev_low and candle["close"] > prev_low:
                result.update(detected=True, type="LOW", level=prev_low, index=i)
        elif htf_bias == "BEARISH":
            # Sweep of the highs: wick pierces above prev_high, close back below.
            if candle["high"] > prev_high and candle["close"] < prev_high:
                result.update(detected=True, type="HIGH", level=prev_high, index=i)
    return result


# ---------------------------------------------------------------------------
# 3. ORDER BLOCK DETECTION (15M)
# ---------------------------------------------------------------------------
def _avg_body(df: pd.DataFrame) -> float:
    """Return the average candle body size for impulse comparison.

    Args:
        df: Candle DataFrame.

    Returns:
        float: Mean absolute (close - open) across the DataFrame.
    """
    return float((df["close"] - df["open"]).abs().mean())


def order_block(m15: pd.DataFrame, htf_bias: str) -> dict:
    """Find a valid order block aligned with the HTF bias.

    Concept: An order block is the last opposite-colour candle before a strong
    impulsive move — the "footprint" left by institutions loading a position.
      • Bullish OB = the last BEARISH candle before a 3+ candle bullish impulse.
      • Bearish OB = the last BULLISH candle before a 3+ candle bearish impulse.
    An impulse is 3 consecutive same-direction candles whose bodies are larger
    than the recent average. The OB is only valid if price has since left the
    zone and not yet returned.

    Args:
        m15: M15 candle DataFrame.
        htf_bias: 'BULLISH' or 'BEARISH'.

    Returns:
        dict: {'valid': bool, 'high': float|None, 'low': float|None,
               'index': int|None}.
    """
    result = {"valid": False, "high": None, "low": None, "index": None}
    if m15 is None or len(m15) < config.IMPULSE_MIN_CANDLES + 2:
        return result

    avg_body = _avg_body(m15)
    n = config.IMPULSE_MIN_CANDLES
    bodies = (m15["close"] - m15["open"]).values

    # Scan from most recent backwards so we return the freshest valid OB.
    for i in range(len(m15) - n - 1, 0, -1):
        impulse = m15.iloc[i + 1:i + 1 + n]
        impulse_bodies = bodies[i + 1:i + 1 + n]

        if htf_bias == "BULLISH":
            bullish_impulse = all(b > 0 for b in impulse_bodies) and \
                all(abs(b) > avg_body for b in impulse_bodies)
            ob_candle = m15.iloc[i]
            is_bearish_ob = ob_candle["close"] < ob_candle["open"]
            if bullish_impulse and is_bearish_ob:
                ob_high, ob_low = float(ob_candle["high"]), float(ob_candle["low"])
                # Valid only if price has not traded back into the zone since.
                after = m15.iloc[i + 1 + n:]
                returned = not after.empty and (after["low"].min() <= ob_high)
                if not returned:
                    result.update(valid=True, high=ob_high, low=ob_low, index=i)
                    return result

        elif htf_bias == "BEARISH":
            bearish_impulse = all(b < 0 for b in impulse_bodies) and \
                all(abs(b) > avg_body for b in impulse_bodies)
            ob_candle = m15.iloc[i]
            is_bullish_ob = ob_candle["close"] > ob_candle["open"]
            if bearish_impulse and is_bullish_ob:
                ob_high, ob_low = float(ob_candle["high"]), float(ob_candle["low"])
                after = m15.iloc[i + 1 + n:]
                returned = not after.empty and (after["high"].max() >= ob_low)
                if not returned:
                    result.update(valid=True, high=ob_high, low=ob_low, index=i)
                    return result

    return result


# ---------------------------------------------------------------------------
# 4. FAIR VALUE GAP CONFIRMATION (5M)
# ---------------------------------------------------------------------------
def fvg(m5: pd.DataFrame, htf_bias: str, ob_zone: dict) -> dict:
    """Detect a Fair Value Gap on M5 that overlaps the order block zone.

    Concept: A Fair Value Gap (FVG) is a 3-candle price imbalance where the
    market moved so fast it left a gap:
      • Bullish FVG: candle[i-1].high < candle[i+1].low (gap below current price).
      • Bearish FVG: candle[i-1].low  > candle[i+1].high (gap above current price).
    Price tends to return to "fill" these gaps, which makes them precise entries.
    We only accept an FVG that aligns with the HTF bias and sits inside (or
    overlaps) the order block zone.

    Args:
        m5: M5 candle DataFrame.
        htf_bias: 'BULLISH' or 'BEARISH'.
        ob_zone: dict from order_block() with 'high'/'low'.

    Returns:
        dict: {'active': bool, 'type': 'BULLISH'|'BEARISH'|None,
               'high': float|None, 'low': float|None, 'index': int|None}.
    """
    result = {"active": False, "type": None, "high": None, "low": None,
              "index": None}
    if m5 is None or len(m5) < 3 or not ob_zone.get("valid"):
        return result

    ob_high, ob_low = ob_zone["high"], ob_zone["low"]

    def _overlaps(g_low: float, g_high: float) -> bool:
        """Return True if a gap [g_low, g_high] overlaps the OB zone."""
        return not (g_high < ob_low or g_low > ob_high)

    # Scan most-recent-first so the freshest gap wins.
    for i in range(len(m5) - 2, 0, -1):
        prev_c = m5.iloc[i - 1]
        next_c = m5.iloc[i + 1]

        if htf_bias == "BULLISH":
            if prev_c["high"] < next_c["low"]:  # bullish imbalance
                g_low, g_high = float(prev_c["high"]), float(next_c["low"])
                if _overlaps(g_low, g_high):
                    result.update(active=True, type="BULLISH", high=g_high,
                                  low=g_low, index=i)
                    return result
        elif htf_bias == "BEARISH":
            if prev_c["low"] > next_c["high"]:  # bearish imbalance
                g_high, g_low = float(prev_c["low"]), float(next_c["high"])
                if _overlaps(g_low, g_high):
                    result.update(active=True, type="BEARISH", high=g_high,
                                  low=g_low, index=i)
                    return result

    return result


def price_in_fvg(price: float, fvg_zone: dict) -> bool:
    """Return whether the current price is inside the FVG zone.

    Args:
        price: Current market price.
        fvg_zone: dict from fvg() with 'low'/'high'.

    Returns:
        bool: True if low <= price <= high and the FVG is active.
    """
    if not fvg_zone.get("active"):
        return False
    return fvg_zone["low"] <= price <= fvg_zone["high"]


# ---------------------------------------------------------------------------
# 5. SIGNAL — combine everything
# ---------------------------------------------------------------------------
def signal(h1: pd.DataFrame, m15: pd.DataFrame, m5: pd.DataFrame,
           current_price: float) -> dict:
    """Run the full top-down analysis and produce a trade signal.

    All of the following must be true to return a tradeable signal:
      • HTF bias is BULLISH or BEARISH (not UNCLEAR).
      • A liquidity sweep against bias occurred within the lookback window.
      • A valid order block aligned with bias exists.
      • An FVG inside that OB, aligned with bias, exists.
      • Current price is inside the FVG zone.

    Args:
        h1: H1 candle DataFrame.
        m15: M15 candle DataFrame.
        m5: M5 candle DataFrame.
        current_price: Latest market price.

    Returns:
        dict: A rich status/signal dict including 'direction'
            ('BUY'/'SELL'/None), each component's result, and 'reason' text.
    """
    out = {
        "direction": None,
        "bias": "UNCLEAR",
        "sweep": {"detected": False},
        "ob": {"valid": False},
        "fvg": {"active": False},
        "price_in_fvg": False,
        "reason": "",
    }

    htf = bias(h1)
    out["bias"] = htf
    if htf == "UNCLEAR":
        out["reason"] = "HTF bias unclear / ranging"
        return out

    sweep_res = sweep(m15, htf)
    out["sweep"] = sweep_res
    if not sweep_res["detected"]:
        out["reason"] = "No liquidity sweep within lookback"
        return out

    ob = order_block(m15, htf)
    out["ob"] = ob
    if not ob["valid"]:
        out["reason"] = "No valid order block aligned with bias"
        return out

    fvg_zone = fvg(m5, htf, ob)
    out["fvg"] = fvg_zone
    if not fvg_zone["active"]:
        out["reason"] = "No FVG inside the order block"
        return out

    if not price_in_fvg(current_price, fvg_zone):
        out["reason"] = "Price not yet inside FVG zone"
        return out

    # Everything aligns — produce the directional signal.
    out["direction"] = "BUY" if htf == "BULLISH" else "SELL"
    out["reason"] = (
        f"{htf} bias + sweep of {sweep_res['type']} + OB "
        f"[{ob['low']:.2f}-{ob['high']:.2f}] + {fvg_zone['type']} FVG entry"
    )
    return out
