"""Orchestrate search -> enrich -> dedup."""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from . import places
from .enrich import enrich_lead
from .models import Lead


def dedupe(leads: Sequence[Lead]) -> List[Lead]:
    """Drop duplicate leads, keeping the first occurrence of each."""
    seen = set()
    unique: List[Lead] = []
    for lead in leads:
        key = lead.dedup_key
        if key in seen:
            continue
        seen.add(key)
        unique.append(lead)
    return unique


def run(
    queries: Sequence[str],
    max_results_per_query: int = 60,
    enrich: bool = True,
    api_key: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Lead]:
    """Full pipeline: search every query, dedupe, then optionally enrich.

    `progress` is an optional callback for status messages (used by the CLI/UI).
    """
    log = progress or (lambda _msg: None)

    raw: List[Lead] = []
    for query in queries:
        log(f"Searching: {query}")
        raw.extend(
            places.search_clinics(
                query, max_results=max_results_per_query, api_key=api_key
            )
        )

    leads = dedupe(raw)
    log(f"Found {len(leads)} unique clinics (from {len(raw)} results).")

    if enrich:
        for i, lead in enumerate(leads, start=1):
            log(f"Enriching {i}/{len(leads)}: {lead.name}")
            enrich_lead(lead)

    return leads
