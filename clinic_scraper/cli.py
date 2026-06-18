"""Command-line interface for the clinic lead scraper.

Examples:
    python -m clinic_scraper.cli "aesthetic clinic in Austin TX"
    python -m clinic_scraper.cli "med spa" --city "Miami FL" --city "Dallas TX"
    python -m clinic_scraper.cli "botox clinic London" --min-score 50 --to-crm
    python -m clinic_scraper.cli "med spa Austin" --niche "Injectables" --niche "Med Spa"
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import crm, export
from .niche import NICHE_KEYWORDS
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
        "--niche",
        action="append",
        choices=list(NICHE_KEYWORDS.keys()),
        help="Keep only these niches. Repeat for several. Default: all targets.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Drop leads with a DM-ready score below this (0-100).",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Keep every result (skip niche/non-target filtering).",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip crawling clinic websites for email/socials.",
    )
    parser.add_argument(
        "--to-crm",
        action="store_true",
        help="Upsert results into the SQLite CRM (leads.db).",
    )
    parser.add_argument(
        "--db",
        default=crm.DEFAULT_DB,
        help=f"CRM database path (default {crm.DEFAULT_DB}).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path stem (no extension). Default: output/leads_<timestamp>.",
    )
    args = parser.parse_args(argv)

    queries = build_queries(args)

    try:
        leads = run(
            queries,
            max_results_per_query=args.max,
            enrich=not args.no_enrich,
            filter_niches=not args.no_filter,
            niches=args.niche,
            min_score=args.min_score,
            progress=lambda msg: print(f"  {msg}", file=sys.stderr),
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not leads:
        print("No clinics matched.", file=sys.stderr)
        return 0

    stem = args.out or f"output/leads_{datetime.now():%Y%m%d_%H%M%S}"
    csv_path = export.to_csv(leads, Path(f"{stem}.csv"))
    xlsx_path = export.to_excel(leads, Path(f"{stem}.xlsx"))

    with_email = sum(1 for lead in leads if lead.email)
    hot = sum(1 for lead in leads if lead.dm_score >= 60)
    print(f"\nDone. {len(leads)} leads ({with_email} with email, {hot} hot >=60).")
    print(f"  CSV:   {csv_path}")
    print(f"  Excel: {xlsx_path}")

    if args.to_crm:
        result = crm.upsert_leads(leads, db_path=args.db)
        print(
            f"  CRM:   {args.db} "
            f"(+{result['inserted']} new, {result['updated']} refreshed)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
