"""Print the clinic names in your CRM (leads.db), highest DM score first.

Usage:
    python list_names.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = "leads.db"

if not Path(DB).exists():
    raise SystemExit(
        "No leads.db found here. Open the app, push some leads to the CRM, "
        "then run this from the same folder."
    )

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT name FROM leads "
    "ORDER BY CAST(COALESCE(dm_score, 0) AS INTEGER) DESC"
).fetchall()
names = [r["name"] for r in rows if r["name"]]

print(f"{len(names)} clinics in your CRM:\n")
for name in names:
    print(name)
