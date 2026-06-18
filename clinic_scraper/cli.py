"""Command-line interface for the clinic lead scraper.

Examples:
    python -m clinic_scraper.cli "aesthetic clinics in Austin TX"
    python -m clinic_scraper.cli "med spa" --city "Miami" --city "Dallas"
    python -m clinic_scraper.cli "botox clinic London" --no-enrich --max 40
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import export
from .pipeline import run


def build_queries(args: argparse.Namespace) -> list[str]:
    if args.city:
        return [f"{args.term} in {city}" for city in args.city]
    return [args.term]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clinic-scraper",
        description="Scrape aesthetic clinic leads from Google Places.",
    )
    parser.add_argument(
        "term",
        help='Search term, e.g. "aesthetic clinic" or "med spa Austin TX".',
    )
    parser.add_argument(
        "--city",
        action="append",
        help="City to scope the search to. Repeat for multiple cities.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=60,
        help="Max results per query (default 60, the API ceiling).",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip crawling clinic websites for email/socials.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path stem (without extension). Default: output/leads_<timestamp>.",
    )
    args = parser.parse_args(argv)

    queries = build_queries(args)

    try:
        leads = run(
            queries,
            max_results_per_query=args.max,
            enrich=not args.no_enrich,
            progress=lambda msg: print(f"  {msg}", file=sys.stderr),
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not leads:
        print("No clinics found.", file=sys.stderr)
        return 0

    stem = args.out or f"output/leads_{datetime.now():%Y%m%d_%H%M%S}"
    csv_path = export.to_csv(leads, Path(f"{stem}.csv"))
    xlsx_path = export.to_excel(leads, Path(f"{stem}.xlsx"))

    with_email = sum(1 for lead in leads if lead.email)
    print(f"\nDone. {len(leads)} leads ({with_email} with email).")
    print(f"  CSV:   {csv_path}")
    print(f"  Excel: {xlsx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
