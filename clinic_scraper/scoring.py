"""DM-ready score: how good a lead is for an AI DM-receptionist pitch.

The pitch is "I answer your Instagram/Facebook DMs 24/7", so the score rewards
clinics that (a) actually have social inboxes, (b) get enough volume to feel the
pain, and (c) are reachable for outreach.

Score is 0-100. The weights live in one place so they're easy to tune.
"""

from __future__ import annotations

from .models import Lead

WEIGHTS = {
    "instagram": 35,   # core: they have an IG inbox to answer
    "facebook": 10,    # another DM channel
    "website": 8,      # established presence
    "email": 15,       # you can actually reach them
    "niche": 12,       # confirmed aesthetic target
}


def _volume_points(reviews: int | None) -> int:
    """Busier clinics get more DMs -> more pain -> better fit."""
    r = reviews or 0
    if r >= 300:
        return 20
    if r >= 150:
        return 15
    if r >= 60:
        return 10
    if r >= 20:
        return 5
    return 0


def _rating_points(rating: float | None) -> int:
    """A solid reputation means real, active demand worth handling."""
    if rating is None:
        return 0
    if rating >= 4.5:
        return 5
    if rating >= 4.0:
        return 3
    return 0


def dm_ready_score(lead: Lead) -> int:
    """Compute the 0-100 DM-ready score for a single lead."""
    score = 0
    if lead.instagram:
        score += WEIGHTS["instagram"]
    if lead.facebook:
        score += WEIGHTS["facebook"]
    if lead.website:
        score += WEIGHTS["website"]
    if lead.email:
        score += WEIGHTS["email"]
    if lead.niche:
        score += WEIGHTS["niche"]
    score += _volume_points(lead.reviews)
    score += _rating_points(lead.rating)
    return min(score, 100)


def score_lead(lead: Lead) -> Lead:
    """Set lead.dm_score in place. Assumes niche is already annotated."""
    lead.dm_score = dm_ready_score(lead)
    return lead
