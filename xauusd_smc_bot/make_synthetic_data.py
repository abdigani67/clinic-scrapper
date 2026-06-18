"""
make_synthetic_data.py — Generate a realistic synthetic XAUUSD M5 dataset.

This is a TEST FIXTURE, not real market data. It produces weekday 24h M5 candles
with regime-switching trends, intraday mean-reversion, and noise so the backtest
harness can be exercised end to end. Use it to validate the engine — NOT to judge
real-world profitability (synthetic data contains no genuine market edge).
"""

import numpy as np
import pandas as pd


def generate(start="2024-06-01", days=365, seed=42) -> pd.DataFrame:
    """Generate synthetic M5 OHLC candles for gold.

    Args:
        start: Start date (UTC).
        days: Number of calendar days to span.
        seed: RNG seed for reproducibility.

    Returns:
        pandas.DataFrame: Columns time, open, high, low, close, tick_volume.
    """
    rng = np.random.default_rng(seed)
    # Build the timestamp index: weekdays only, full 24h in 5-min steps.
    all_min = pd.date_range(start=start, periods=days * 288, freq="5min", tz="UTC")
    mask = all_min.dayofweek < 5  # drop Sat/Sun
    idx = all_min[mask]

    n = len(idx)
    price = 3000.0
    trend = 0.0
    regime_len = 0
    vol = 0.8  # per-bar volatility in price units

    opens = np.empty(n)
    highs = np.empty(n)
    lows = np.empty(n)
    closes = np.empty(n)
    vols = np.empty(n)

    for i in range(n):
        # Regime switching: occasionally flip into a trend up/down or range.
        if regime_len <= 0:
            regime_len = int(rng.integers(150, 900))  # bars per regime
            choice = rng.choice(["up", "down", "range"], p=[0.35, 0.35, 0.30])
            trend = {"up": 0.10, "down": -0.10, "range": 0.0}[choice]
            vol = float(rng.uniform(0.5, 1.4))
        regime_len -= 1

        # Intraday vol smile: higher vol around the NY open hours (12-21 UTC).
        hour = idx[i].hour
        session_boost = 1.4 if 12 <= hour <= 21 else 0.7

        step = trend + rng.normal(0, vol * session_boost)
        o = price
        c = price + step
        # Wms: wicks scale with volatility.
        wick = abs(rng.normal(0, vol * session_boost))
        h = max(o, c) + wick
        l = min(o, c) - abs(rng.normal(0, vol * session_boost))
        opens[i], highs[i], lows[i], closes[i] = o, h, l, c
        vols[i] = abs(step) * 1000 + 100
        price = c
        # Soft mean reversion to keep price in a plausible band.
        if price > 3600:
            trend = -abs(trend) - 0.05
        elif price < 2600:
            trend = abs(trend) + 0.05

    df = pd.DataFrame({
        "time": idx.tz_localize(None),
        "open": opens.round(2),
        "high": highs.round(2),
        "low": lows.round(2),
        "close": closes.round(2),
        "tick_volume": vols.round(0),
    })
    return df


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_xauusd_m5.csv"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 365
    data = generate(days=days)
    data.to_csv(out, index=False)
    print(f"Wrote {len(data):,} M5 candles to {out} "
          f"({data['time'].iloc[0]} -> {data['time'].iloc[-1]})")
