"""
main.py — Entry point and main control loop for the XAUUSD SMC trading bot.

Plain English: this is the conductor. It connects to MT5, then loops forever:
every cycle it refreshes market structure, checks whether all the safety filters
(session, news, daily loss, existing trade) are clear, asks the strategy module
for a signal, and — if everything lines up — sizes and places the trade. It then
monitors the open position until it closes, prints a status block every 5
minutes, reconnects automatically if the link drops, and shuts down cleanly on
Ctrl+C.

This is a REAL-MONEY trading bot: reliability and error handling are prioritised
over cleverness. Every external call is wrapped so one hiccup never crashes the
whole bot.
"""

import time

import config
import mt5_client as mt5c
import news
import risk
import strategies
import strategy
from utils import (
    fmt_est,
    log_error,
    log_trade,
    now_est,
    print_status,
    session_open,
)


class BotState:
    """Holds mutable run-time state shared across loop cycles.

    Attributes:
        opening_balance: Balance recorded at the start of the current NY day.
        opening_day: The EST date string the opening_balance belongs to.
        halted_for_day: True once the daily loss limit has stopped trading.
        last_status_ts: Monotonic time of the last status print.
        last_bias_ts: Monotonic time of the last H1/M15 recheck.
        last_trade_summary: Human string describing the most recent closed trade.
        cached: Cache of the latest analysis components for status printing.
    """

    def __init__(self):
        self.opening_balance = 0.0
        self.opening_day = None
        self.halted_for_day = False
        self.last_status_ts = 0.0
        self.last_bias_ts = 0.0
        self.last_trade_summary = "—"
        self.cached = {"bias": "UNCLEAR", "sweep": False, "ob": "—", "fvg": "NO",
                       "signal": "NONE"}


def _roll_day_if_needed(state: BotState) -> None:
    """Reset per-day state when a new NY trading day begins.

    Records the opening balance for the new day and clears the daily-loss halt.

    Args:
        state: The shared BotState.

    Returns:
        None.
    """
    today = now_est().strftime("%Y-%m-%d")
    if state.opening_day != today:
        state.opening_day = today
        state.opening_balance = mt5c.get_balance()
        state.halted_for_day = False


def _monitor_open_position(state: BotState) -> None:
    """Check whether the open position has closed and log the result if so.

    SL/TP are attached to the order itself, so the broker closes the position;
    here we simply detect the transition from "open" to "closed" and journal it.

    Args:
        state: The shared BotState.

    Returns:
        None.
    """
    if mt5c.has_open_position():
        return  # Still open — nothing to do this cycle.

    # If we previously had a position flagged, record its outcome.
    realised = mt5c.get_today_closed_pnl(_day_start_dt())
    balance = mt5c.get_balance()
    state.last_trade_summary = (
        f"{'WIN' if realised >= 0 else 'LOSS'} {realised:+.2f}"
    )
    # Note: detailed per-trade logging happens at entry; this keeps the summary
    # fresh for the status block.


def _day_start_dt():
    """Return a datetime at the start of the current EST day.

    Returns:
        datetime: EST midnight today (timezone-aware).
    """
    return now_est().replace(hour=0, minute=0, second=0, microsecond=0)


def _try_enter_trade(state: BotState) -> None:
    """Run the full analysis and place a trade if all conditions are met.

    Args:
        state: The shared BotState.

    Returns:
        None.
    """
    # --- Hard safety gates first (cheap checks) ---------------------------
    if mt5c.has_open_position():
        state.cached["signal"] = "IN TRADE"
        return

    if not session_open():
        state.cached["signal"] = "SESSION CLOSED"
        return

    if news.in_news_window():
        state.cached["signal"] = "NEWS BLOCK"
        return

    # --- Daily loss limit -------------------------------------------------
    realised = mt5c.get_today_closed_pnl(_day_start_dt())
    floating = mt5c.get_floating_pnl()
    if risk.daily_loss_hit(state.opening_balance, realised, floating):
        state.halted_for_day = True
    if state.halted_for_day:
        state.cached["signal"] = "DAILY LOSS HALT"
        return

    # --- Pull market data -------------------------------------------------
    h1 = mt5c.get_candles("H1", config.H1_CANDLES)
    m15 = mt5c.get_candles("M15", config.M15_CANDLES)
    m5 = mt5c.get_candles("M5", config.M5_CANDLES)
    if h1 is None or m15 is None or m5 is None:
        state.cached["signal"] = "NO DATA"
        return

    # Ask the selected strategy for a direction. The SMC strategy returns a rich
    # dict (and populates the bias/sweep/OB/FVG status fields); the other
    # strategies just return a direction.
    last_price = float(m5["close"].iloc[-1])
    if config.STRATEGY_NAME == "smc":
        sig = strategy.signal(h1, m15, m5, last_price)
        state.cached["bias"] = sig["bias"]
        state.cached["sweep"] = "YES" if sig["sweep"].get("detected") else "NO"
        if sig["ob"].get("valid"):
            state.cached["ob"] = f"{sig['ob']['low']:.2f} – {sig['ob']['high']:.2f}"
        else:
            state.cached["ob"] = "—"
        state.cached["fvg"] = "YES" if sig["fvg"].get("active") else "NO"
        direction = sig["direction"]
        no_signal_reason = sig["reason"]
    else:
        direction = strategies.live_direction(config.STRATEGY_NAME, h1, m15, m5)
        state.cached["bias"] = config.STRATEGY_NAME
        state.cached["sweep"] = "—"
        state.cached["ob"] = "—"
        state.cached["fvg"] = "—"
        no_signal_reason = f"No {config.STRATEGY_NAME} signal"

    if direction is None:
        state.cached["signal"] = no_signal_reason
        return

    state.cached["signal"] = f"{'LONG' if direction == 'BUY' else 'SHORT'} PENDING"

    # --- Use the live tradeable price for SL/TP/sizing --------------------
    entry = mt5c.get_current_price(direction)
    if entry is None:
        state.cached["signal"] = "NO PRICE"
        return

    point = mt5c.get_point()

    sl = risk.stop_loss(direction, entry, m15, point)
    if sl is None:
        state.cached["signal"] = "SL OUT OF RANGE"
        return

    tp, rr = risk.take_profit(direction, entry, sl, m15, point)

    balance = mt5c.get_balance()
    risk.init_scaling(balance)
    sizing_base = risk.scaling_base(balance)
    lot = risk.position_size(sizing_base, entry, sl, point)
    if lot <= 0:
        state.cached["signal"] = "LOT TOO SMALL"
        return

    # --- Place the order --------------------------------------------------
    result = mt5c.place_order(direction, lot, sl, tp)
    if not result["success"]:
        log_error(f"Entry failed: {result['comment']}")
        state.cached["signal"] = "ORDER REJECTED"
        return

    fill_price = result["price"]
    now = now_est()
    log_trade({
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "direction": direction,
        "entry_price": round(fill_price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "rr": rr,
        "lot_size": lot,
        "result": "OPEN",
        "pnl": "",
        "balance_after": round(balance, 2),
        "entry_reason": sig["reason"],
    })
    state.cached["signal"] = f"{direction} FILLED @ {fill_price:.2f}"
    print(f"✅ Placed {direction} {lot} lots @ {fill_price:.2f} "
          f"SL {sl:.2f} TP {tp:.2f} (RR {rr})")


def _print_periodic_status(state: BotState) -> None:
    """Print the formatted status block (rate-limited to every 5 minutes).

    Args:
        state: The shared BotState.

    Returns:
        None.
    """
    now_ts = time.monotonic()
    if now_ts - state.last_status_ts < config.LOOP_INTERVAL:
        return
    state.last_status_ts = now_ts

    balance = mt5c.get_balance()
    realised = mt5c.get_today_closed_pnl(_day_start_dt())
    floating = mt5c.get_floating_pnl()
    daily_pnl = realised + floating

    print_status({
        "time_est": fmt_est(),
        "session": "OPEN" if session_open() else "CLOSED",
        "news": news.status_label(),
        "bias": state.cached["bias"],
        "sweep": state.cached["sweep"],
        "ob_zone": state.cached["ob"],
        "fvg": state.cached["fvg"],
        "signal": state.cached["signal"],
        "balance": f"{balance:.2f}",
        "daily_pnl": f"{daily_pnl:+.2f}",
        "last_trade": state.last_trade_summary,
    })


def run() -> None:
    """Start the bot: connect, then loop until interrupted.

    Returns:
        None.
    """
    print("Starting XAUUSD SMC Bot…")
    print(f"Mode: {'DEMO' if config.DEMO_MODE else 'LIVE'}  "
          f"Server: {config.resolve_server()}")

    if not mt5c.connect():
        log_error("Initial MT5 connection failed. Exiting.")
        return

    state = BotState()
    _roll_day_if_needed(state)
    risk.init_scaling(state.opening_balance)
    print("Connected. Entering main loop. Press Ctrl+C to stop.\n")

    try:
        while True:
            try:
                # Auto-reconnect if the link dropped.
                if not mt5c.is_connected():
                    log_error("MT5 connection lost — attempting reconnect.")
                    if not mt5c.reconnect():
                        log_error("Reconnect failed after retries. Stopping.")
                        break

                _roll_day_if_needed(state)

                # Periodically refresh the slower structure (H1/M15). The data
                # is re-pulled inside _try_enter_trade each cycle anyway; this
                # timestamp simply documents the cadence requirement.
                now_ts = time.monotonic()
                if now_ts - state.last_bias_ts >= config.BIAS_INTERVAL:
                    state.last_bias_ts = now_ts

                _monitor_open_position(state)
                _try_enter_trade(state)
                _print_periodic_status(state)

            except Exception as exc:  # noqa: BLE001 - never let the loop die
                log_error(f"Unhandled error in loop cycle: {exc}")

            # Sleep between cycles (M5 cadence).
            time.sleep(config.LOOP_INTERVAL)

    except KeyboardInterrupt:
        print("\nCtrl+C received — shutting down gracefully…")
    finally:
        mt5c.disconnect()
        print("MT5 connection closed. Goodbye.")


if __name__ == "__main__":
    run()
