"""
risk.py — Position sizing, stop-loss / take-profit construction, the daily loss
limit, and the auto-scaling logic.

Plain English: this module decides "how big should this trade be?" and "where do
my stop-loss and take-profit go?" so that a single bad trade only ever risks the
small percentage you configured. It also enforces a daily stop-loss for the whole
account and automatically scales position sizing as the account grows.
"""

import json
import math
import os

import config
from utils import log_error

# Small file used to persist the initial balance and current scaling base across
# restarts, so the "double the account -> rebase sizing" rule survives reboots.
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "account_state.json")


# ---------------------------------------------------------------------------
# Persistent scaling state
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    """Load the persisted account scaling state.

    Returns:
        dict: {'initial_balance': float|None, 'scaling_base': float|None}.
    """
    if os.path.isfile(_STATE_FILE):
        try:
            with open(_STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            log_error(f"Could not read account_state.json: {exc}")
    return {"initial_balance": None, "scaling_base": None}


def _save_state(state: dict) -> None:
    """Persist the account scaling state to disk.

    Args:
        state: Dict to serialise.

    Returns:
        None.
    """
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError as exc:
        log_error(f"Could not write account_state.json: {exc}")


def init_scaling(balance: float) -> None:
    """Record the initial balance on first ever run.

    Args:
        balance: The account balance observed at startup.

    Returns:
        None.
    """
    state = _load_state()
    if state.get("initial_balance") is None:
        state["initial_balance"] = balance
        state["scaling_base"] = balance
        _save_state(state)


def scaling_base(balance: float) -> float:
    """Return the balance used as the base for position sizing.

    Scaling rule: when the live balance reaches >= 2x the current scaling base,
    we rebase to the new balance. This compounds sizing automatically as the
    account doubles — no manual input needed.

    Args:
        balance: Current account balance.

    Returns:
        float: The balance figure to use in the position-size formula.
    """
    state = _load_state()
    base = state.get("scaling_base") or balance
    if balance >= 2 * base:
        state["scaling_base"] = balance
        _save_state(state)
        base = balance
    return base


# ---------------------------------------------------------------------------
# Stop loss / take profit
# ---------------------------------------------------------------------------
def stop_loss(direction: str, entry: float, m15, point: float) -> float | None:
    """Compute the stop-loss price from recent M15 swing structure.

    For LONGS: SL = lowest low of the last SL_SWING_LOOKBACK M15 candles, minus a
    SL_BUFFER_POINTS buffer. For SHORTS: highest high plus the buffer.

    The resulting SL distance must be between MIN_SL_POINTS and MAX_SL_POINTS or
    the trade is skipped (returns None).

    Args:
        direction: 'BUY' or 'SELL'.
        entry: Intended entry price.
        m15: M15 candle DataFrame.
        point: Symbol point size (e.g. 0.01 for XAUUSD).

    Returns:
        float | None: Stop-loss price, or None if the distance is out of bounds.
    """
    recent = m15.iloc[-config.SL_SWING_LOOKBACK:]
    buffer_price = config.SL_BUFFER_POINTS * point

    if direction == "BUY":
        sl_price = float(recent["low"].min()) - buffer_price
    else:
        sl_price = float(recent["high"].max()) + buffer_price

    distance_points = abs(entry - sl_price) / point
    if distance_points < config.MIN_SL_POINTS:
        log_error(f"SL too tight ({distance_points:.0f} pts) — skipping trade.")
        return None
    if distance_points > config.MAX_SL_POINTS:
        log_error(f"SL too wide ({distance_points:.0f} pts) — skipping trade.")
        return None
    return sl_price


def take_profit(direction: str, entry: float, sl: float, m15,
                point: float) -> tuple:
    """Compute the take-profit price using a 1:3 default, extended to 1:4.

    Concept: We aim for at least 3x the risk. If the previous session's high/low
    (a natural liquidity target) lies beyond the 1:3 level, we extend the target
    to 1:4 to capture the move to that liquidity — but we always take the more
    conservative (closer) of the two so we never overshoot a realistic target.

    Args:
        direction: 'BUY' or 'SELL'.
        entry: Entry price.
        sl: Stop-loss price.
        m15: M15 candle DataFrame (for the previous session high/low).
        point: Symbol point size.

    Returns:
        tuple(float, float): (take_profit_price, realised_rr).
    """
    sl_distance = abs(entry - sl)

    # Default 1:3 target.
    if direction == "BUY":
        tp_default = entry + sl_distance * config.RR_DEFAULT
        tp_extended = entry + sl_distance * config.RR_EXTENDED
    else:
        tp_default = entry - sl_distance * config.RR_DEFAULT
        tp_extended = entry - sl_distance * config.RR_EXTENDED

    # Previous-session liquidity target (older half of the window).
    half = len(m15) // 2
    prev = m15.iloc[:half] if half > 0 else m15
    prev_high = float(prev["high"].max())
    prev_low = float(prev["low"].min())
    liquidity_target = prev_high if direction == "BUY" else prev_low

    # Decide whether liquidity lies beyond the 1:3 level (worth extending to 1:4).
    extend = False
    if direction == "BUY" and liquidity_target > tp_default:
        extend = True
    elif direction == "SELL" and liquidity_target < tp_default:
        extend = True

    if extend:
        # Take the more conservative of the extended target and the liquidity
        # level (closer to entry) so we set a target price we can actually reach.
        if direction == "BUY":
            tp = min(tp_extended, liquidity_target)
        else:
            tp = max(tp_extended, liquidity_target)
    else:
        tp = tp_default

    rr = abs(tp - entry) / sl_distance if sl_distance else 0.0
    return tp, round(rr, 2)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------
def position_size(balance: float, entry: float, sl: float, point: float) -> float:
    """Calculate lot size so the trade risks RISK_PERCENT of the account.

    Formula: (balance × risk%) ÷ (SL distance in points × point value per lot).
    The result is rounded DOWN to the nearest lot step and clamped between the
    minimum and maximum lot size.

    Args:
        balance: Balance used for sizing (post-scaling base).
        entry: Entry price.
        sl: Stop-loss price.
        point: Symbol point size.

    Returns:
        float: Lot size, or 0.0 if the trade cannot be sized (caller skips).
    """
    sl_distance_points = abs(entry - sl) / point
    if sl_distance_points <= 0:
        return 0.0

    risk_amount = balance * (config.RISK_PERCENT / 100.0)
    # Money lost per 1.00 lot if SL is hit = distance_points × value-per-point.
    loss_per_lot = sl_distance_points * config.POINT_VALUE_PER_LOT
    if loss_per_lot <= 0:
        return 0.0

    raw_lot = risk_amount / loss_per_lot

    # Round DOWN to the nearest lot step.
    steps = math.floor(raw_lot / config.LOT_STEP)
    lot = steps * config.LOT_STEP

    if lot < config.MIN_LOT:
        log_error(f"Computed lot {lot:.2f} below minimum — skipping trade.")
        return 0.0
    lot = min(lot, config.MAX_LOT)
    return round(lot, 2)


# ---------------------------------------------------------------------------
# Daily loss limit
# ---------------------------------------------------------------------------
def daily_loss_hit(opening_balance: float, realised_pnl: float,
                   floating_pnl: float) -> bool:
    """Return whether the daily loss limit has been breached.

    The limit is DAILY_LOSS_LIMIT percent of the day's opening balance, measured
    against realised + floating PnL combined.

    Args:
        opening_balance: Balance at the start of the trading day.
        realised_pnl: Closed PnL so far today.
        floating_pnl: Current unrealised PnL on open positions.

    Returns:
        bool: True if trading should halt for the rest of the day.
    """
    if opening_balance <= 0:
        return False
    limit_amount = opening_balance * (config.DAILY_LOSS_LIMIT / 100.0)
    total = realised_pnl + floating_pnl
    return total <= -abs(limit_amount)
