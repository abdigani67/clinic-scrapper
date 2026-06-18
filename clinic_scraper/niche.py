"""Classify clinics into aesthetic niches and filter out non-targets.

Classification uses the clinic name, the search query, and the Google Places
`types`. A lead is considered a target if it matches at least one aesthetic
niche, or its Places types clearly mark it as a spa/beauty/medical business.
"""

from __future__ import annotations

import re
from typing import List

from .models import Lead

# Aesthetic niches -> trigger keywords (matched against name + query, lowercased).
NICHE_KEYWORDS = {
    "Injectables": [
        "botox", "dysport", "jeuveau", "xeomin", "tox", "filler", "dermal filler",
        "lip filler", "injectable", "sculptra", "kybella", "anti-wrinkle",
        "anti wrinkle", "wrinkle", "lip enhancement",
    ],
    "Laser & Skin": [
        "laser", "ipl", "hair removal", "photofacial", "resurfacing", "morpheus",
        "co2 laser", "pico",
    ],
    "Facials & Skincare": [
        "facial", "hydrafacial", "chemical peel", "peel", "microneedling",
        "dermaplaning", "skincare", "skin care", "skin clinic", "esthetic",
        "esthetician", "aesthetician",
    ],
    "Med Spa": [
        "med spa", "medspa", "medi spa", "medical spa", "medi-spa", "aesthetic",
        "aesthetics", "rejuven",
    ],
    "Body Contouring": [
        "coolsculpting", "body contour", "emsculpt", "sculpt", "cellulite",
        "fat reduction", "liposuction", "lipo",
    ],
    "Cosmetic Surgery": [
        "plastic surgery", "plastic surgeon", "cosmetic surgery", "cosmetic surgeon",
        "rhinoplasty", "facelift", "breast augmentation",
    ],
    "Wellness & IV": [
        "iv therapy", "iv drip", "wellness", "hormone", "weight loss", "semaglutide",
        "ozempic", "peptide",
    ],
    "Dermatology": ["dermatology", "dermatologist", "derm "],
}

# Google Places types that signal a plausible aesthetic/beauty/medical business.
TARGET_PLACE_TYPES = {
    "beauty_salon",
    "spa",
    "wellness_center",
    "medical_clinic",
    "skin_care_clinic",
    "doctor",
    "health",
}

# If a lead matches these and matches NO aesthetic niche, it's almost certainly
# not a target and gets dropped.
EXCLUDE_KEYWORDS = [
    "dental", "dentist", "orthodont", "endodont", "veterinary", "vet clinic",
    "animal hospital", "gym", "fitness", "crossfit", "yoga studio", "barber",
    "nail salon", "nails", "tattoo", "chiropract", "physical therapy",
    "physiotherapy", "urgent care", "pediatric", "optometr", "eye care",
    "veterinarian", "pharmacy", "car ", "auto ", "law firm", "attorney",
]


def _haystack(lead: Lead) -> str:
    # Classify on the clinic NAME only. The search query is the same for every
    # result in a search, so including it just creates false positives (e.g. a
    # dentist returned by an "aesthetic clinic" search inheriting "aesthetic").
    return lead.name.lower()


def classify_niches(lead: Lead) -> List[str]:
    """Return the list of aesthetic niches a lead matches (may be empty)."""
    text = _haystack(lead)
    matched = []
    for niche, keywords in NICHE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(niche)
    return matched


def is_target(lead: Lead, niches: List[str] | None = None) -> bool:
    """Decide whether a lead is a genuine aesthetic-clinic target."""
    niches = classify_niches(lead) if niches is None else niches
    if niches:
        return True

    text = _haystack(lead)
    if any(re.search(re.escape(kw), text) for kw in EXCLUDE_KEYWORDS):
        return False

    # No explicit niche keyword, but Places types mark it as spa/beauty/medical.
    return bool(set(lead.place_types) & TARGET_PLACE_TYPES)


def annotate(lead: Lead) -> Lead:
    """Set lead.niche from classification (in place)."""
    lead.niche = ", ".join(classify_niches(lead))
    return lead
