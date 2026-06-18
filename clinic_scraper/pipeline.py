"""Orchestrate search -> filter -> enrich -> score."""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from . import niche as niche_mod
from . import places, scoring
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
    filter_niches: bool = True,
    niches: Optional[Sequence[str]] = None,
    min_score: int = 0,
    api_key: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Lead]:
    """Full pipeline.

    Steps: search -> dedupe -> niche filter -> enrich -> score -> score filter.

    Args:
        filter_niches: drop leads that aren't aesthetic-clinic targets.
        niches: if given, keep only leads matching one of these niche names.
        min_score: drop leads whose final DM-ready score is below this.
        progress: optional callback for status messages (CLI/UI).
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
    log(f"Found {len(leads)} unique places (from {len(raw)} results).")

    # Niche classification + filtering.
    kept: List[Lead] = []
    for lead in leads:
        matched = niche_mod.classify_niches(lead)
        if filter_niches and not niche_mod.is_target(lead, matched):
            continue
        if niches and not (set(matched) & set(niches)):
            continue
        niche_mod.annotate(lead)
        kept.append(lead)
    if filter_niches or niches:
        log(f"{len(kept)} clinics matched your niche filter.")
    leads = kept

    if enrich:
        for i, lead in enumerate(leads, start=1):
            log(f"Enriching {i}/{len(leads)}: {lead.name}")
            enrich_lead(lead)

    # Score after enrichment (email/socials feed the score), then filter + sort.
    for lead in leads:
        scoring.score_lead(lead)
    if min_score:
        before = len(leads)
        leads = [lead for lead in leads if lead.dm_score >= min_score]
        log(f"{len(leads)}/{before} clinics scored >= {min_score}.")

    leads.sort(key=lambda lead: lead.dm_score, reverse=True)
    return leads
