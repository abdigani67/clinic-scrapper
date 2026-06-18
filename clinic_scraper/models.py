"""Data model for a single clinic lead."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional


# Order here defines the column order in CSV/Excel exports.
# (place_types is internal-only and intentionally excluded.)
LEAD_FIELDS = [
    "name",
    "dm_score",
    "niche",
    "address",
    "phone",
    "email",
    "website",
    "instagram",
    "instagram_handle",
    "facebook",
    "tiktok",
    "rating",
    "reviews",
    "google_maps_url",
    "place_id",
    "query",
]


@dataclass
class Lead:
    """A single aesthetic clinic lead."""

    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    instagram: str = ""
    instagram_handle: str = ""
    facebook: str = ""
    tiktok: str = ""
    rating: Optional[float] = None
    reviews: Optional[int] = None
    google_maps_url: str = ""
    place_id: str = ""
    query: str = ""
    # Derived fields, populated by the niche/scoring stages.
    niche: str = ""
    dm_score: int = 0
    # Internal only (not exported): Google Places type tags.
    place_types: List[str] = field(default_factory=list)

    def as_row(self) -> dict:
        """Flat dict in LEAD_FIELDS order, ready for CSV/Excel."""
        data = asdict(self)
        return {key: data.get(key, "") for key in LEAD_FIELDS}

    @property
    def dedup_key(self) -> str:
        """Stable identity used to avoid duplicate leads across runs.

        Prefer the Google place_id; fall back to a normalized name+address.
        """
        if self.place_id:
            return f"place:{self.place_id}"
        norm = re.sub(r"\s+", " ", f"{self.name} {self.address}".lower()).strip()
        return f"name:{norm}"
