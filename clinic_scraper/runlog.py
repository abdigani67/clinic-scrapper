"""Append-only log of scrape runs, so results can be tracked over time.

Writes one row per city per run to a CSV: date, source, city, clinics found,
how many were enriched (got email/socials), with email, with Instagram.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

from .models import Lead

DEFAULT_LOG = "scrape_log.csv"

FIELDS = [
    "timestamp",
    "source",
    "city",
    "found",
    "enriched",
    "with_email",
    "with_instagram",
]


def _city(query: str) -> str:
    return query.rsplit(" in ", 1)[-1].strip() if " in " in query else query.strip()


def summarize(
    leads: Sequence[Lead], source: str, queries: Sequence[str]
) -> List[dict]:
    """Build one summary row per city/query for a finished run."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows: List[dict] = []
    for query in queries:
        group = [lead for lead in leads if lead.query == query]
        rows.append(
            {
                "timestamp": stamp,
                "source": source,
                "city": _city(query),
                "found": len(group),
                "enriched": sum(
                    1
                    for lead in group
                    if lead.email or lead.instagram or lead.facebook or lead.tiktok
                ),
                "with_email": sum(1 for lead in group if lead.email),
                "with_instagram": sum(1 for lead in group if lead.instagram),
            }
        )
    return rows


def log_run(rows: Sequence[dict], path: str | Path = DEFAULT_LOG) -> None:
    """Append summary rows to the log CSV (creates it with a header if new)."""
    path = Path(path)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_log(path: str | Path = DEFAULT_LOG) -> List[dict]:
    """Return all logged rows (newest first), or [] if there's no log yet."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))
