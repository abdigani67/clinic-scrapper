"""Google Places API (New) client for finding clinics.

Uses the Text Search endpoint, which returns name, address, phone, website,
rating and review count in a single call (with an appropriate field mask).
"""

from __future__ import annotations

import time
from typing import Iterator, List, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config
from .models import Lead

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Only request the fields we actually export — keeps responses small and cost low.
FIELD_MASK = ",".join(
    "places." + f
    for f in [
        "id",
        "displayName",
        "formattedAddress",
        "internationalPhoneNumber",
        "nationalPhoneNumber",
        "websiteUri",
        "rating",
        "userRatingCount",
        "googleMapsUri",
        "types",
    ]
)


# Only retry transient network errors — not 4xx client errors, which won't
# fix themselves (a 403 just means "not enabled / billing off").
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _post(payload: dict, api_key: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK + ",nextPageToken",
    }
    resp = requests.post(
        TEXT_SEARCH_URL,
        json=payload,
        headers=headers,
        timeout=config.REQUEST_TIMEOUT,
    )
    if 400 <= resp.status_code < 500:
        # Surface Google's own explanation instead of a raw traceback.
        try:
            message = resp.json().get("error", {}).get("message", "")
        except ValueError:
            message = resp.text[:200]
        hint = ""
        if resp.status_code == 403:
            hint = (
                " — this usually means the 'Places API (New)' isn't enabled or "
                "billing isn't active on your Google Cloud project."
            )
        elif resp.status_code in (400, 401):
            hint = " — check that your GOOGLE_PLACES_API_KEY is correct."
        raise RuntimeError(
            f"Google Places API error {resp.status_code}: {message}{hint}"
        )
    resp.raise_for_status()  # 5xx -> retried as a transient error
    return resp.json()


def _place_to_lead(place: dict, query: str) -> Lead:
    return Lead(
        name=(place.get("displayName") or {}).get("text", ""),
        address=place.get("formattedAddress", ""),
        phone=place.get("internationalPhoneNumber")
        or place.get("nationalPhoneNumber", ""),
        website=place.get("websiteUri", ""),
        rating=place.get("rating"),
        reviews=place.get("userRatingCount"),
        google_maps_url=place.get("googleMapsUri", ""),
        place_id=place.get("id", ""),
        query=query,
        place_types=place.get("types", []) or [],
    )


def search_clinics(
    query: str,
    max_results: int = 60,
    api_key: Optional[str] = None,
) -> List[Lead]:
    """Search clinics for a text query, e.g. "aesthetic clinics in Austin TX".

    Handles pagination. The API returns up to 20 results per page and up to
    3 pages (~60 results) per query, so refine queries by city for coverage.
    """
    api_key = api_key or config.require_api_key()
    leads: List[Lead] = []
    page_token: Optional[str] = None

    while len(leads) < max_results:
        payload: dict = {"textQuery": query, "pageSize": 20}
        if page_token:
            payload["pageToken"] = page_token

        data = _post(payload, api_key)
        for place in data.get("places", []):
            leads.append(_place_to_lead(place, query))

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        # nextPageToken needs a brief moment before it becomes valid.
        time.sleep(2)

    return leads[:max_results]


def search_many(
    queries: Iterator[str],
    max_results_per_query: int = 60,
    api_key: Optional[str] = None,
) -> List[Lead]:
    """Run several queries (e.g. one per city) and concatenate results."""
    api_key = api_key or config.require_api_key()
    all_leads: List[Lead] = []
    for query in queries:
        all_leads.extend(
            search_clinics(query, max_results=max_results_per_query, api_key=api_key)
        )
    return all_leads
