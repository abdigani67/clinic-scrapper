"""Orchestrate search -> filter -> enrich -> score."""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from . import niche as niche_mod
from . import foursquare, osm, places, scoring
from .enrich import enrich_lead, finalize_socials
from .models import Lead

# Available clinic data sources, mapped to their search function.
SOURCES = {
    "google": places.search_clinics,
    "osm": osm.search_clinics,
    "foursquare": foursquare.search_clinics,
}


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
    source: str = "google",
    api_key: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Lead]:
    """Full pipeline.

    Steps: search -> dedupe -> niche filter -> enrich -> score -> score filter.

    Args:
        source: which data source to search ("google" or "osm").
        filter_niches: drop leads that aren't aesthetic-clinic targets.
        niches: if given, keep only leads matching one of these niche names.
        min_score: drop leads whose final DM-ready score is below this.
        progress: optional callback for status messages (CLI/UI).
    """
    log = progress or (lambda _msg: None)
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}. Valid: {list(SOURCES)}")
    search = SOURCES[source]

    raw: List[Lead] = []
    for query in queries:
        log(f"Searching ({source}): {query}")
        raw.extend(
            search(query, max_results=max_results_per_query, api_key=api_key)
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

    # Normalize Instagram to a clean profile URL + @handle (covers both
    # sources and leads with no website), then score.
    for lead in leads:
        finalize_socials(lead)
        scoring.score_lead(lead)
    if min_score:
        before = len(leads)
        leads = [lead for lead in leads if lead.dm_score >= min_score]
        log(f"{len(leads)}/{before} clinics scored >= {min_score}.")

    leads.sort(key=lambda lead: lead.dm_score, reverse=True)
    return leads
