"""
compare.py — Backtest every candidate strategy and rank them.

Runs each strategy in strategies.py through the SAME risk engine, session and
news filters, then prints a ranked comparison table so you can see which entry
logic performs best on your data. The winner can be wired into the live bot via
STRATEGY_NAME in config.py.

Usage:
    python compare.py path/to/xauusd_m5.csv --balance 100 --data-tz UTC
"""

from __future__ import annotations

import argparse

import backtest as bt
import config
import strategies
import utils
from strategies import STRATEGIES


def _score(stats: dict) -> float:
    """Rank key: profit factor, penalised by drawdown, needs enough trades.

    Strategies with too few trades (<20) are deprioritised because their stats
    are not statistically meaningful.

    Args:
        stats: Output of backtest.compute_stats.

    Returns:
        float: A sortable score (higher is better).
    """
    if stats.get("trades", 0) < 20:
        return -1e9 + stats.get("trades", 0)
    pf = stats["profit_factor"]
    pf = 5.0 if pf == float("inf") else pf
    dd = max(stats["max_drawdown_pct"], 1.0)
    return stats["return_pct"] / dd + pf


def main(argv=None) -> int:
    """Run the strategy comparison and print a ranked table.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Compare XAUUSD strategies.")
    parser.add_argument("csv", help="Path to M5 candle CSV.")
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--data-tz", default="UTC")
    parser.add_argument("--commission", type=float, default=7.0)
    parser.add_argument("--spread-points", type=float, default=10.0)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--no-news", action="store_true")
    parser.add_argument("--max-sl", type=float, default=None,
                        help="Override MAX_SL_POINTS (gold swings need ~2000-3000).")
    parser.add_argument("--min-sl", type=float, default=None,
                        help="Override MIN_SL_POINTS.")
    parser.add_argument("--risk", type=float, default=None,
                        help="Override RISK_PERCENT.")
    parser.add_argument("--verbose", action="store_true",
                        help="Show per-trade skip warnings (noisy).")
    args = parser.parse_args(argv)

    # Apply optional risk overrides so strategies can be compared without the
    # capital/stop bottleneck masking their true edge.
    if args.max_sl is not None:
        config.MAX_SL_POINTS = args.max_sl
    if args.min_sl is not None:
        config.MIN_SL_POINTS = args.min_sl
    if args.risk is not None:
        config.RISK_PERCENT = args.risk
    if not args.verbose:
        # risk.py bound `log_error` at import, so patch it there too.
        _quiet = lambda *a, **k: None  # noqa: E731
        utils.log_error = _quiet
        bt.risk.log_error = _quiet

    print(f"Risk: {config.RISK_PERCENT}%  SL bounds: "
          f"{config.MIN_SL_POINTS}-{config.MAX_SL_POINTS} pts  "
          f"Balance: {args.balance}")
    print(f"Loading {args.csv} (tz={args.data_tz})...")
    m5 = bt.load_m5_csv(args.csv, args.data_tz)
    m15 = bt.resample(m5, "15min")
    h1 = bt.resample(m5, "1h")
    print(f"Loaded {len(m5):,} M5 candles "
          f"({m5.index[0].date()} -> {m5.index[-1].date()}).\n")

    rows = []
    for name, func in STRATEGIES.items():
        signals = func(m5, m15, h1)
        result = bt.run_with_signals(
            m5, signals,
            starting_balance=args.balance,
            commission_per_lot=args.commission,
            spread_points=args.spread_points,
            apply_session=not args.no_session,
            apply_news=not args.no_news,
        )
        stats = bt.compute_stats(result)
        stats["_name"] = name
        stats["_score"] = _score(stats) if stats.get("trades", 0) else -1e9
        rows.append(stats)
        n = stats.get("trades", 0)
        print(f"  {name:12s} trades={n:4d}  "
              f"{'(too few)' if n < 20 else ''}")

    rows.sort(key=lambda s: s["_score"], reverse=True)

    print("\n" + "=" * 78)
    print(f"{'STRATEGY':12s} {'TRADES':>7s} {'WIN%':>6s} {'PF':>6s} "
          f"{'RETURN%':>9s} {'MAXDD%':>7s} {'EXPECT':>8s} {'END BAL':>9s}")
    print("=" * 78)
    for s in rows:
        if s.get("trades", 0) == 0:
            print(f"{s['_name']:12s} {'0':>7s}   (no trades)")
            continue
        pf = s["profit_factor"]
        pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
        print(f"{s['_name']:12s} {s['trades']:>7d} {s['win_rate']:>5.1f}% "
              f"{pf_str:>6s} {s['return_pct']:>+8.1f}% {s['max_drawdown_pct']:>6.1f}% "
              f"{s['expectancy']:>+8.2f} {s['ending_balance']:>9.2f}")
    print("=" * 78)

    best = next((s for s in rows if s.get("trades", 0) >= 20), None)
    if best:
        bpf = best["profit_factor"]
        bpf_str = "inf" if bpf == float("inf") else f"{bpf:.2f}"
        name = best["_name"]
        print(f"\nBest by score: {name.upper()}  "
              f"(return {best['return_pct']:+.1f}%, PF {bpf_str}, "
              f"maxDD {best['max_drawdown_pct']:.1f}%)")
        print(f'Set STRATEGY_NAME = "{name}" in config.py to run it live.')
    else:
        print("\nNo strategy produced a statistically meaningful number of trades.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
