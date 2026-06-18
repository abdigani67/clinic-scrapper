"""
news.py — Red-folder news filter with a safe-mode fallback.

Plain English: high-impact ("red folder") economic news — like US Non-Farm
Payrolls or CPI — causes violent, unpredictable price spikes. We do NOT want to
be entering trades around those moments. This module downloads the week's news
calendar from ForexFactory, keeps only the USD / Gold high-impact events, and
tells the bot whether *right now* is inside a no-trade window (30 minutes before
to 60 minutes after any such event).

If the download fails for any reason, we fall back to "safe mode": a hardcoded
list of the usual high-impact release times, treated with the same buffers.
"""

from datetime import datetime, timedelta

import requests

import config
from utils import EST, log_error, now_est


# Cache the parsed events so we are not hammering the feed on every loop cycle.
_cached_events: list[datetime] = []
_cache_date: str | None = None
_using_safe_mode = False


def _fetch_raw_events() -> list[dict]:
    """Download and parse this week's ForexFactory calendar.

    Returns:
        list[dict]: Raw event dicts from the JSON feed.

    Raises:
        Exception: Propagates network/parse errors to the caller so it can
            decide to fall back to safe mode.
    """
    resp = requests.get(config.FOREXFACTORY_FEED_URL, timeout=15,
                        headers={"User-Agent": "Mozilla/5.0 (SMC-Bot)"})
    resp.raise_for_status()
    return resp.json()


def _parse_event_time(event: dict) -> datetime | None:
    """Convert a ForexFactory event's date string into an EST datetime.

    The faireconomy feed publishes an ISO-8601 ``date`` field that already
    includes a timezone offset. We normalise it into America/New_York.

    Args:
        event: A single raw event dict from the feed.

    Returns:
        datetime | None: Timezone-aware EST datetime, or None if unparseable.
    """
    raw = event.get("date")
    if not raw:
        return None
    try:
        # Python's fromisoformat handles the trailing offset (e.g. -04:00).
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = EST.localize(dt)
        return dt.astimezone(EST)
    except (ValueError, TypeError):
        return None


def _is_relevant(event: dict) -> bool:
    """Return whether an event is a high-impact USD or Gold event.

    Args:
        event: Raw event dict from the feed.

    Returns:
        bool: True if impact is 'High'/'red' AND currency is USD (gold is priced
            in USD, so USD news is what moves XAUUSD).
    """
    impact = str(event.get("impact", "")).lower()
    currency = str(event.get("country", event.get("currency", ""))).upper()
    is_high = impact in ("high", "red")
    is_relevant_ccy = currency in ("USD", "XAU", "GOLD")
    return is_high and is_relevant_ccy


def refresh_events() -> bool:
    """Refresh the cached list of relevant red-folder event times.

    Populates the module cache once per calendar day. On failure, switches the
    module into safe mode (hardcoded times for today).

    Returns:
        bool: True if live events were loaded, False if safe mode is active.
    """
    global _cached_events, _cache_date, _using_safe_mode

    today = now_est().strftime("%Y-%m-%d")
    if _cache_date == today and _cached_events:
        return not _using_safe_mode

    try:
        raw = _fetch_raw_events()
        events = []
        for ev in raw:
            if not _is_relevant(ev):
                continue
            dt = _parse_event_time(ev)
            if dt is not None:
                events.append(dt)
        _cached_events = events
        _cache_date = today
        _using_safe_mode = False
        return True
    except Exception as exc:  # noqa: BLE001 - any failure -> safe mode
        log_error(f"News fetch failed, entering SAFE MODE: {exc}")
        _cached_events = _safe_mode_events()
        _cache_date = today
        _using_safe_mode = True
        return False


def _safe_mode_events() -> list[datetime]:
    """Build today's hardcoded safe-mode event times in EST.

    Returns:
        list[datetime]: EST datetimes for each hardcoded high-impact slot today.
    """
    base = now_est().replace(second=0, microsecond=0)
    events = []
    for hhmm in config.SAFE_MODE_NEWS_TIMES:
        hour, minute = (int(x) for x in hhmm.split(":"))
        events.append(base.replace(hour=hour, minute=minute))
    return events


def in_news_window(check_time: datetime | None = None) -> bool:
    """Return whether ``check_time`` falls inside any news no-trade window.

    A window spans NEWS_BUFFER_BEFORE minutes before an event to
    NEWS_BUFFER_AFTER minutes after it.

    Args:
        check_time: EST datetime to test. Defaults to now (EST).

    Returns:
        bool: True if trading should be blocked due to news.
    """
    if check_time is None:
        check_time = now_est()

    # Make sure we have a current event list (or safe-mode list).
    refresh_events()

    before = timedelta(minutes=config.NEWS_BUFFER_BEFORE)
    after = timedelta(minutes=config.NEWS_BUFFER_AFTER)

    for event_dt in _cached_events:
        if (event_dt - before) <= check_time <= (event_dt + after):
            return True
    return False


def status_label() -> str:
    """Return a short label for the console status block.

    Returns:
        str: 'BLOCKED', 'BLOCKED (SAFE)', or 'CLEAR'.
    """
    blocked = in_news_window()
    if blocked and _using_safe_mode:
        return "BLOCKED (SAFE)"
    if blocked:
        return "BLOCKED"
    return "CLEAR"
