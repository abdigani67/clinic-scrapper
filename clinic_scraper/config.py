"""Configuration loaded from environment / .env."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
FOURSQUARE_API_KEY = os.getenv("FOURSQUARE_API_KEY", "").strip()

# Polite defaults so we don't hammer clinic websites.
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "15"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; ClinicLeadBot/0.1; +https://example.com/bot)",
)


def require_api_key() -> str:
    """Return the Places API key or raise a clear error."""
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Copy .env.example to .env and "
            "add your Google Places API (New) key."
        )
    return GOOGLE_PLACES_API_KEY
