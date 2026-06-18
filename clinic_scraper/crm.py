"""SQLite-backed CRM for clinic leads.

Stores scraped lead data alongside CRM workflow fields (status + notes).
Re-scraping the same clinic refreshes the scraped fields but PRESERVES your
CRM edits (status, notes, created_at) via an upsert keyed on dedup_key.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .models import LEAD_FIELDS, Lead

DEFAULT_DB = "leads.db"

# CRM pipeline stages, in order.
STATUSES = ["new", "contacted", "replied", "demo", "won", "lost"]

# Scraped columns refreshed on re-scrape (everything except CRM/workflow fields).
_SCRAPED_COLS = list(LEAD_FIELDS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB) -> None:
    """Create the leads table if it doesn't exist."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                dedup_key       TEXT PRIMARY KEY,
                name            TEXT,
                dm_score        INTEGER DEFAULT 0,
                niche           TEXT,
                address         TEXT,
                phone           TEXT,
                email           TEXT,
                website         TEXT,
                instagram        TEXT,
                instagram_handle TEXT,
                facebook        TEXT,
                tiktok          TEXT,
                rating          REAL,
                reviews         INTEGER,
                google_maps_url TEXT,
                place_id        TEXT,
                query           TEXT,
                status          TEXT DEFAULT 'new',
                notes           TEXT DEFAULT '',
                created_at      TEXT,
                updated_at      TEXT
            )
            """
        )
        # Migrate older databases: add any expected column that doesn't exist.
        expected = LEAD_FIELDS + ["status", "notes", "created_at", "updated_at"]
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
        for col in expected:
            if col not in existing:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT")


def upsert_leads(leads: Iterable[Lead], db_path: str | Path = DEFAULT_DB) -> dict:
    """Insert new leads / refresh existing ones. Returns {inserted, updated}."""
    init_db(db_path)
    inserted = updated = 0

    with _connect(db_path) as conn:
        for lead in leads:
            row = lead.as_row()
            key = lead.dedup_key
            exists = conn.execute(
                "SELECT 1 FROM leads WHERE dedup_key = ?", (key,)
            ).fetchone()

            if exists:
                set_clause = ", ".join(f"{col} = ?" for col in _SCRAPED_COLS)
                params = [row[col] for col in _SCRAPED_COLS] + [_now(), key]
                conn.execute(
                    f"UPDATE leads SET {set_clause}, updated_at = ? "
                    f"WHERE dedup_key = ?",
                    params,
                )
                updated += 1
            else:
                cols = ["dedup_key"] + _SCRAPED_COLS + [
                    "status", "notes", "created_at", "updated_at"
                ]
                values = (
                    [key]
                    + [row[col] for col in _SCRAPED_COLS]
                    + ["new", "", _now(), _now()]
                )
                placeholders = ", ".join("?" for _ in cols)
                conn.execute(
                    f"INSERT INTO leads ({', '.join(cols)}) VALUES ({placeholders})",
                    values,
                )
                inserted += 1

    return {"inserted": inserted, "updated": updated}


def list_leads(
    db_path: str | Path = DEFAULT_DB,
    status: Optional[str] = None,
    niche: Optional[str] = None,
    min_score: int = 0,
    order_by: str = "CAST(COALESCE(dm_score, 0) AS INTEGER) DESC",
) -> List[dict]:
    """Return leads as dicts, with optional filters."""
    init_db(db_path)
    # CAST + COALESCE so the comparison is numeric even when dm_score was
    # added as a TEXT column by an older-DB migration (and NULLs count as 0).
    clauses, params = ["CAST(COALESCE(dm_score, 0) AS INTEGER) >= ?"], [min_score]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if niche:
        clauses.append("niche LIKE ?")
        params.append(f"%{niche}%")

    where = " AND ".join(clauses)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM leads WHERE {where} ORDER BY {order_by}", params
        ).fetchall()
    return [dict(r) for r in rows]


def update_status(
    dedup_key: str, status: str, db_path: str | Path = DEFAULT_DB
) -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}. Valid: {STATUSES}")
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE leads SET status = ?, updated_at = ? WHERE dedup_key = ?",
            (status, _now(), dedup_key),
        )


def update_notes(
    dedup_key: str, notes: str, db_path: str | Path = DEFAULT_DB
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE leads SET notes = ?, updated_at = ? WHERE dedup_key = ?",
            (notes, _now(), dedup_key),
        )


def stats(db_path: str | Path = DEFAULT_DB) -> dict:
    """Return total count and a per-status breakdown."""
    init_db(db_path)
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        by_status = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM leads GROUP BY status"
            ).fetchall()
        }
    return {"total": total, "by_status": by_status}
