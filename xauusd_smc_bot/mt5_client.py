"""
mt5_client.py — Every interaction with the MetaTrader5 terminal lives here.

Plain English: this is the "phone line" to your broker. It connects to the
running MT5 terminal, pulls candle data, reads your balance and open trades, and
sends buy/sell orders. Keeping all MT5 calls in one file means the strategy code
never has to know the messy details of the trading API.
"""

import time

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - allows import on non-Windows dev boxes
    mt5 = None

import config
from utils import log_error

# Map friendly timeframe names to MT5 constants. Done lazily so the module can be
# imported even where MetaTrader5 is unavailable (e.g. CI / Linux dev machine).
def _timeframe(tf_name: str):
    """Translate a timeframe label ('H1','M15','M5') to the MT5 constant.

    Args:
        tf_name: One of 'H1', 'M15', 'M5'.

    Returns:
        The MetaTrader5 timeframe constant.
    """
    return {
        "H1": mt5.TIMEFRAME_H1,
        "M15": mt5.TIMEFRAME_M15,
        "M5": mt5.TIMEFRAME_M5,
    }[tf_name]


def connect() -> bool:
    """Initialise and log in to the MT5 terminal.

    Uses credentials and server from config (which loads them from .env). The
    MT5 terminal must already be running and logged in on the same machine.

    Returns:
        bool: True if connection + login succeeded, False otherwise.
    """
    if mt5 is None:
        log_error("MetaTrader5 library not installed — cannot connect.")
        return False

    server = config.resolve_server()

    # initialize() launches/attaches to the terminal. Pass the path only if set.
    init_ok = (
        mt5.initialize(path=config.MT5_TERMINAL_PATH)
        if config.MT5_TERMINAL_PATH
        else mt5.initialize()
    )
    if not init_ok:
        log_error(f"mt5.initialize() failed: {mt5.last_error()}")
        return False

    # login() authenticates the account on the connected terminal.
    if not mt5.login(
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=server,
    ):
        log_error(f"mt5.login() failed for server {server}: {mt5.last_error()}")
        mt5.shutdown()
        return False

    # Make sure the symbol is visible/selected in Market Watch.
    if not mt5.symbol_select(config.SYMBOL, True):
        log_error(f"Could not select symbol {config.SYMBOL}: {mt5.last_error()}")
        return False

    return True


def reconnect() -> bool:
    """Attempt to re-establish the MT5 connection with retries.

    Tries up to config.MAX_RECONNECT_ATTEMPTS times with a short pause between
    attempts. Used by the main loop when the connection drops mid-run.

    Returns:
        bool: True if reconnection succeeded within the allowed attempts.
    """
    for attempt in range(1, config.MAX_RECONNECT_ATTEMPTS + 1):
        log_error(f"Reconnect attempt {attempt}/{config.MAX_RECONNECT_ATTEMPTS}...")
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001 - shutdown is best-effort
            pass
        if connect():
            return True
        time.sleep(5 * attempt)
    return False


def disconnect() -> None:
    """Cleanly close the MT5 connection. Safe to call multiple times.

    Returns:
        None.
    """
    if mt5 is not None:
        try:
            mt5.shutdown()
        except Exception as exc:  # noqa: BLE001
            log_error(f"Error during mt5.shutdown(): {exc}")


def is_connected() -> bool:
    """Check whether the terminal is still reachable.

    Returns:
        bool: True if terminal_info() responds, False if the link is down.
    """
    if mt5 is None:
        return False
    return mt5.terminal_info() is not None


def get_candles(timeframe: str, count: int) -> pd.DataFrame | None:
    """Fetch the most recent ``count`` candles for the configured symbol.

    Args:
        timeframe: 'H1', 'M15', or 'M5'.
        count: Number of candles to retrieve, counting back from the latest.

    Returns:
        pandas.DataFrame | None: Columns time, open, high, low, close,
        tick_volume (time converted to datetime). None on failure.
    """
    rates = mt5.copy_rates_from_pos(config.SYMBOL, _timeframe(timeframe), 0, count)
    if rates is None or len(rates) == 0:
        log_error(f"copy_rates_from_pos returned no data for {timeframe}: "
                  f"{mt5.last_error()}")
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_symbol_info():
    """Return the MT5 SymbolInfo object for the configured symbol.

    Returns:
        The SymbolInfo named tuple, or None if unavailable.
    """
    info = mt5.symbol_info(config.SYMBOL)
    if info is None:
        log_error(f"symbol_info failed for {config.SYMBOL}: {mt5.last_error()}")
    return info


def get_point() -> float:
    """Return the symbol's point size (smallest price increment).

    Returns:
        float: The point value (e.g. 0.01 for XAUUSD), or 0.01 as a fallback.
    """
    info = get_symbol_info()
    return float(info.point) if info else 0.01


def get_current_price(direction: str) -> float | None:
    """Return the price to trade at for the given direction.

    Buys fill at the ask, sells fill at the bid.

    Args:
        direction: 'BUY' or 'SELL'.

    Returns:
        float | None: The relevant price, or None if no tick is available.
    """
    tick = mt5.symbol_info_tick(config.SYMBOL)
    if tick is None:
        log_error(f"symbol_info_tick failed: {mt5.last_error()}")
        return None
    return tick.ask if direction == "BUY" else tick.bid


def get_balance() -> float:
    """Return the current account balance.

    Returns:
        float: Account balance, or 0.0 if account info is unavailable.
    """
    info = mt5.account_info()
    if info is None:
        log_error(f"account_info failed: {mt5.last_error()}")
        return 0.0
    return float(info.balance)


def get_equity() -> float:
    """Return current account equity (balance + floating PnL).

    Returns:
        float: Account equity, or 0.0 if unavailable.
    """
    info = mt5.account_info()
    if info is None:
        log_error(f"account_info failed: {mt5.last_error()}")
        return 0.0
    return float(info.equity)


def get_open_positions() -> list:
    """Return a list of open positions on the configured symbol.

    Returns:
        list: MT5 position objects (possibly empty).
    """
    positions = mt5.positions_get(symbol=config.SYMBOL)
    if positions is None:
        return []
    return list(positions)


def has_open_position() -> bool:
    """Return whether there is at least one open position on the symbol.

    Returns:
        bool: True if a position is currently open.
    """
    return len(get_open_positions()) > 0


def get_today_closed_pnl(since_dt) -> float:
    """Sum realised profit from deals closed since the given datetime.

    Args:
        since_dt: timezone-aware datetime marking the start of the window.

    Returns:
        float: Total realised PnL (profit + swap + commission) since since_dt.
    """
    deals = mt5.history_deals_get(since_dt, _now_server_dt())
    if deals is None:
        return 0.0
    total = 0.0
    for d in deals:
        if getattr(d, "symbol", "") == config.SYMBOL:
            total += float(d.profit) + float(d.swap) + float(d.commission)
    return total


def get_floating_pnl() -> float:
    """Return the sum of floating (unrealised) profit on open positions.

    Returns:
        float: Floating PnL across open positions on the symbol.
    """
    return sum(float(p.profit) for p in get_open_positions())


def _now_server_dt():
    """Return a naive 'now' datetime suitable for MT5 history queries.

    MT5 history functions expect server-time datetimes; using the local UTC-ish
    now with a generous window is sufficient for an intraday day-PnL sum.

    Returns:
        datetime: Current datetime (naive).
    """
    from datetime import datetime, timedelta

    # Add a day of slack to be safe against server/local time differences.
    return datetime.now() + timedelta(days=1)


def close_position(position) -> bool:
    """Close an open position with an opposing market order.

    Used for the intraday end-of-day exit so nothing is held overnight.

    Args:
        position: An MT5 position object from positions_get().

    Returns:
        bool: True if the close order was accepted.
    """
    # Opposite side closes the position; sells hit the bid, buys the ask.
    is_buy = position.type == mt5.ORDER_TYPE_BUY
    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(config.SYMBOL)
    if tick is None:
        log_error("close_position: no tick available.")
        return False
    price = tick.bid if is_buy else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": config.SYMBOL,
        "volume": float(position.volume),
        "type": close_type,
        "position": position.ticket,
        "price": price,
        "deviation": config.ORDER_DEVIATION,
        "magic": config.MAGIC_NUMBER,
        "comment": "SMC_BOT_EOD_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log_error(f"close_position failed: "
                  f"{getattr(result, 'comment', mt5.last_error())}")
        return False
    return True


def close_all_positions() -> int:
    """Close every open position on the configured symbol.

    Returns:
        int: Number of positions successfully closed.
    """
    closed = 0
    for pos in get_open_positions():
        if close_position(pos):
            closed += 1
    return closed


def place_order(direction: str, lot: float, sl: float, tp: float) -> dict:
    """Send a market order and confirm whether it filled.

    Args:
        direction: 'BUY' or 'SELL'.
        lot: Position size in lots (already validated/rounded by risk module).
        sl: Stop-loss price.
        tp: Take-profit price.

    Returns:
        dict: {'success': bool, 'price': float|None, 'retcode': int|None,
               'comment': str, 'ticket': int|None}.
    """
    price = get_current_price(direction)
    if price is None:
        return {"success": False, "price": None, "retcode": None,
                "comment": "no price tick", "ticket": None}

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": config.SYMBOL,
        "volume": float(lot),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "deviation": config.ORDER_DEVIATION,
        "magic": config.MAGIC_NUMBER,
        "comment": config.ORDER_COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        log_error(f"order_send returned None: {mt5.last_error()}")
        return {"success": False, "price": price, "retcode": None,
                "comment": "order_send None", "ticket": None}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_error(f"Order rejected: retcode={result.retcode} "
                  f"comment={result.comment}")
        return {"success": False, "price": price, "retcode": result.retcode,
                "comment": result.comment, "ticket": None}

    # Confirm fill by checking that a position now exists.
    filled = has_open_position()
    if not filled:
        log_error("order_send reported DONE but no open position found.")

    return {
        "success": filled,
        "price": float(result.price) if result.price else price,
        "retcode": result.retcode,
        "comment": result.comment,
        "ticket": int(result.order) if result.order else None,
    }
