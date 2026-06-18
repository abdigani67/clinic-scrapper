"""Free clinic data source using OpenStreetMap (no API key, no billing).

Two public, free services are used:
  * Nominatim  - turns a city name into a bounding box (geocoding).
  * Overpass   - returns businesses (beauty, spa, clinic) inside that box.

OSM has no star ratings / review counts, so those fields stay empty; the
website-enrichment and scoring steps still run as usual.
"""

from __future__ import annotations

import time
from typing import List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config
from .models import Lead

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Several free Overpass mirrors. The main instance often returns 406/429 under
# load, so we try them in order and use the first that answers.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# OSM tag -> a pseudo Places "type" our niche.is_target() already understands.
TAG_TYPE_MAP = {
    ("shop", "beauty"): "beauty_salon",
    ("leisure", "spa"): "spa",
    ("amenity", "spa"): "spa",
    ("healthcare", "clinic"): "medical_clinic",
    ("amenity", "clinic"): "medical_clinic",
    ("healthcare", "cosmetic_surgery"): "medical_clinic",
    ("healthcare", "dermatology"): "skin_care_clinic",
}


def _headers() -> dict:
    # Nominatim/Overpass etiquette: identify the client.
    return {"User-Agent": config.USER_AGENT}


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    reraise=True,
)
def _geocode(location: str) -> Optional[tuple]:
    """Return (south, west, north, east) bounding box for a place name."""
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": location, "format": "json", "limit": 1},
        headers=_headers(),
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    # Nominatim boundingbox is [south, north, west, east] as strings.
    s, n, w, e = (float(x) for x in results[0]["boundingbox"])
    return (s, w, n, e)


def _overpass(bbox: tuple) -> list:
    """Run an Overpass query, trying each mirror until one succeeds."""
    south, west, north, east = bbox
    box = f"({south},{west},{north},{east})"
    selectors = "".join(
        f'nwr["{k}"="{v}"]{box};' for (k, v) in TAG_TYPE_MAP
    )
    ql = f"[out:json][timeout:60];({selectors});out tags center;"

    last_error: Optional[Exception] = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint,
                data={"data": ql},
                headers=_headers(),
                timeout=max(config.REQUEST_TIMEOUT, 60),
            )
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            continue

    raise RuntimeError(
        "All OpenStreetMap (Overpass) servers were busy or unreachable. "
        "Please wait a minute and try again. "
        f"(last error: {last_error})"
    )


def _location_from_query(query: str) -> str:
    """Extract the place name. App builds queries like '<term> in <city>'."""
    if " in " in query:
        return query.rsplit(" in ", 1)[-1].strip()
    return query.strip()


def _address(tags: dict) -> str:
    parts = [
        " ".join(
            p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p
        ),
        tags.get("addr:city"),
        tags.get("addr:state"),
        tags.get("addr:postcode"),
    ]
    return ", ".join(p for p in parts if p)


def _social_url(value: str, base: str) -> str:
    """OSM stores socials as either a full URL or a bare handle."""
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return base + value.lstrip("@/")


def _element_to_lead(el: dict, query: str) -> Lead:
    tags = el.get("tags", {})
    pseudo_types = [
        TAG_TYPE_MAP[(k, v)]
        for (k, v) in TAG_TYPE_MAP
        if tags.get(k) == v
    ]
    return Lead(
        name=tags.get("name", ""),
        address=_address(tags),
        phone=tags.get("phone") or tags.get("contact:phone", ""),
        email=tags.get("email") or tags.get("contact:email", ""),
        website=tags.get("website") or tags.get("contact:website", ""),
        instagram=_social_url(
            tags.get("contact:instagram", ""), "https://instagram.com/"
        ),
        facebook=_social_url(
            tags.get("contact:facebook", ""), "https://facebook.com/"
        ),
        google_maps_url="",
        place_id=f"osm-{el.get('type')}-{el.get('id')}",
        query=query,
        place_types=pseudo_types,
    )


def search_clinics(
    query: str,
    max_results: int = 60,
    api_key: Optional[str] = None,  # unused; kept for interface parity
) -> List[Lead]:
    """Find clinics for a query like 'med spa in Austin TX' via OpenStreetMap."""
    location = _location_from_query(query)
    bbox = _geocode(location)
    if not bbox:
        return []

    time.sleep(1)  # be gentle between Nominatim and Overpass
    elements = _overpass(bbox)

    leads: List[Lead] = []
    for el in elements:
        if not el.get("tags", {}).get("name"):
            continue  # skip unnamed entries
        leads.append(_element_to_lead(el, query))
    return leads[:max_results]
