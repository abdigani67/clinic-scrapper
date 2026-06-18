"""Foursquare Places API data source (free key, no billing card required).

Uses the current Foursquare Places API:
  GET https://places-api.foursquare.com/places/search
with a Service Key ("Authorization: Bearer <key>") and a dated API version
header. Good global coverage, including the UK.

Get a free key at https://foursquare.com/developers/ (no credit card needed).
"""

from __future__ import annotations

import re
from typing import List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config
from .models import Lead

SEARCH_URL = "https://places-api.foursquare.com/places/search"
API_VERSION = "2025-06-17"

# Fields we ask Foursquare to return (smaller responses, lower cost).
FIELDS = "fsq_place_id,name,location,tel,website,social_media,categories"

# Category-name keywords -> pseudo Places type our niche filter understands.
_CATEGORY_TYPES = [
    ("spa", "spa"),
    ("salon", "beauty_salon"),
    ("beauty", "beauty_salon"),
    ("cosmetic", "skin_care_clinic"),
    ("dermatolog", "skin_care_clinic"),
    ("skin", "skin_care_clinic"),
    ("surgeon", "medical_clinic"),
    ("doctor", "medical_clinic"),
    ("medical", "medical_clinic"),
    ("health", "medical_clinic"),
    ("clinic", "medical_clinic"),
]
# Aesthetic-sounding names always count as a target (recall safety net).
_NAME_MATCH_RE = re.compile(
    "botox|filler|aesthetic|medspa|med spa|skin|laser|cosmetic|dermatolog|"
    "injectable|rejuven|wrinkle|hydrafacial|dermal|clinic",
    re.IGNORECASE,
)


def _require_key(api_key: Optional[str]) -> str:
    key = api_key or config.FOURSQUARE_API_KEY
    if not key:
        raise RuntimeError(
            "FOURSQUARE_API_KEY is not set. Get a free key (no card) at "
            "https://foursquare.com/developers/ and add it to your .env file."
        )
    return key


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    reraise=True,
)
def _get(params: dict, key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {key}",
        "X-Places-Api-Version": API_VERSION,
        "Accept": "application/json",
    }
    resp = requests.get(
        SEARCH_URL, params=params, headers=headers, timeout=config.REQUEST_TIMEOUT
    )
    if resp.status_code == 401:
        raise RuntimeError(
            "Foursquare rejected the API key (401). Make sure it's a Service "
            "Key from the new Foursquare developer console."
        )
    resp.raise_for_status()
    return resp.json()


def _location_from_query(query: str) -> str:
    return query.rsplit(" in ", 1)[-1].strip() if " in " in query else query.strip()


def _term_from_query(query: str) -> str:
    return query.rsplit(" in ", 1)[0].strip() if " in " in query else query.strip()


def _pseudo_types(result: dict) -> list:
    name = result.get("name", "")
    cats = " ".join(c.get("name", "") for c in result.get("categories", [])).lower()
    types = [t for kw, t in _CATEGORY_TYPES if kw in cats]
    if _NAME_MATCH_RE.search(name):
        types.append("skin_care_clinic")
    return list(dict.fromkeys(types))


def _social(result: dict, kind: str, base: str) -> str:
    value = (result.get("social_media") or {}).get(kind, "")
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return base + str(value).lstrip("@/")


def _result_to_lead(result: dict, query: str) -> Lead:
    loc = result.get("location") or {}
    return Lead(
        name=result.get("name", ""),
        address=loc.get("formatted_address", ""),
        phone=result.get("tel", ""),
        website=result.get("website", ""),
        instagram=_social(result, "instagram", "https://instagram.com/"),
        facebook=_social(result, "facebook_id", "https://facebook.com/"),
        place_id=f"fsq-{result.get('fsq_place_id') or result.get('fsq_id', '')}",
        query=query,
        place_types=_pseudo_types(result),
    )


def search_clinics(
    query: str,
    max_results: int = 50,
    api_key: Optional[str] = None,
) -> List[Lead]:
    """Find clinics for a query like 'aesthetic clinic in Bristol UK'."""
    key = _require_key(api_key)
    params = {
        "query": _term_from_query(query),
        "near": _location_from_query(query),
        "limit": min(max_results, 50),  # Foursquare caps a page at 50
    }
    data = _get(params, key)
    results = data.get("results", [])
    return [_result_to_lead(r, query) for r in results if r.get("name")]
