"""Realistic sample leads for exploring the UI without an API key.

These are fictional clinics — they let you see the table, scores, filters and
CRM flow before you wire up a real Google Places key.
"""

from __future__ import annotations

from typing import List

from . import niche as niche_mod
from . import scoring
from .enrich import finalize_socials
from .models import Lead

_RAW = [
    dict(
        name="Glow Aesthetics & Med Spa", address="120 Congress Ave, Austin, TX",
        phone="+1 512-555-0142", email="hello@glowaesthetics.com",
        website="https://glowaesthetics.example",
        instagram="https://instagram.com/glowaesthetics",
        facebook="https://facebook.com/glowaesthetics",
        rating=4.9, reviews=412, place_id="demo-1", query="med spa in Austin TX",
    ),
    dict(
        name="Lumière Botox & Filler Bar", address="88 SW 8th St, Miami, FL",
        phone="+1 305-555-0178", email="book@lumierebar.com",
        website="https://lumierebar.example",
        instagram="https://instagram.com/lumierebar",
        rating=4.7, reviews=233, place_id="demo-2", query="botox clinic in Miami FL",
    ),
    dict(
        name="Radiance Laser & Skin Clinic", address="500 Main St, Dallas, TX",
        phone="+1 214-555-0190", email="",
        website="https://radianceskin.example",
        instagram="https://instagram.com/radianceskin",
        rating=4.5, reviews=98, place_id="demo-3", query="laser clinic in Dallas TX",
    ),
    dict(
        name="Contour Body Sculpting Studio", address="22 Brickell Ave, Miami, FL",
        phone="+1 305-555-0133", email="info@contourstudio.com",
        website="https://contourstudio.example",
        facebook="https://facebook.com/contourstudio",
        rating=4.6, reviews=64, place_id="demo-4",
        query="body contouring in Miami FL",
    ),
    dict(
        name="Pure Dermatology & Cosmetic Surgery",
        address="7 Park Pl, Austin, TX", phone="+1 512-555-0101",
        email="contact@purederm.com", website="https://purederm.example",
        rating=4.4, reviews=176, place_id="demo-5",
        query="dermatology in Austin TX",
    ),
    dict(
        name="The Skin Lab", address="900 Elm St, Dallas, TX",
        phone="+1 214-555-0166", email="", website="",
        rating=4.2, reviews=15, place_id="demo-6", query="skincare in Dallas TX",
        place_types=["beauty_salon"],
    ),
]


def sample_leads() -> List[Lead]:
    """Return demo leads, niche-annotated and scored like a real run."""
    leads = [Lead(**row) for row in _RAW]
    for lead in leads:
        niche_mod.annotate(lead)
        finalize_socials(lead)
        scoring.score_lead(lead)
    leads.sort(key=lambda lead: lead.dm_score, reverse=True)
    return leads
