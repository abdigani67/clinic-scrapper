"""Generate natural, low-pressure outreach drafts for a clinic lead.

Produces an Instagram DM and an email (subject + body) personalised with the
clinic's name and niche. Deliberately warm and human — no hype, no hard sell.
Pick of phrasing is deterministic per clinic so drafts stay stable.
"""

from __future__ import annotations

from typing import Dict

DEFAULT_SENDER = "[Your name]"

# Niche -> a natural phrase to reference their work.
_NICHE_PHRASE = {
    "Injectables": "your injectable work",
    "Laser & Skin": "your laser and skin treatments",
    "Facials & Skincare": "your skincare treatments",
    "Med Spa": "what you're doing at the clinic",
    "Body Contouring": "your body treatments",
    "Cosmetic Surgery": "your cosmetic work",
    "Wellness & IV": "your wellness treatments",
    "Dermatology": "your skin treatments",
}
_DEFAULT_PHRASE = "what you're doing at the clinic"


def _phrase(niche: str) -> str:
    first = (niche or "").split(",")[0].strip()
    return _NICHE_PHRASE.get(first, _DEFAULT_PHRASE)


def _pick(name: str, options: list) -> str:
    """Deterministic choice so the same clinic always gets the same draft."""
    return options[sum(ord(c) for c in name) % len(options)]


def draft_dm(name: str, niche: str = "", sender: str = DEFAULT_SENDER) -> str:
    name = name or "there"
    phrase = _phrase(niche)
    options = [
        (
            f"Hi {name} 👋 I've been following {phrase} and it looks brilliant. "
            "Quick question — when an enquiry lands in your DMs while you're with "
            "a client, who picks it up? I help aesthetic clinics reply to those "
            "instantly, day or night, so none get missed. Would it be ok to show "
            "you a quick example?"
        ),
        (
            f"Hey {name}! Really like what you're doing with {phrase}. I work with "
            "clinics to make sure no DM enquiry goes unanswered — even evenings "
            "and weekends. Not trying to sell you anything today, just wondered if "
            "missed messages is something you've run into?"
        ),
        (
            f"Hi {name} 😊 Came across your clinic and {phrase} stood out. Out of "
            "interest, how do you currently handle Instagram enquiries when things "
            "get busy? I set clinics up with something that replies and books "
            "people in automatically — happy to share more if it'd be useful."
        ),
    ]
    return _pick(name, options)


def draft_email(
    name: str, niche: str = "", sender: str = DEFAULT_SENDER
) -> Dict[str, str]:
    name = name or "there"
    phrase = _phrase(niche)
    subject = _pick(
        name,
        [
            f"Quick question about {name}'s enquiries",
            f"A thought for {name}",
            f"Helping {name} catch every enquiry",
        ],
    )
    body = (
        f"Hi {name} team,\n\n"
        f"I came across your clinic and really liked {phrase}.\n\n"
        "I wanted to ask — when enquiries come in through Instagram or your "
        "website outside of clinic hours, who tends to respond? A lot of the "
        "clinics I speak to quietly lose potential bookings simply because "
        "messages aren't seen until the next day.\n\n"
        "I help clinics with an assistant that replies to DMs and enquiries "
        "instantly, around the clock — it answers the common questions and books "
        "consultations straight into the calendar, all in your clinic's tone.\n\n"
        "No hard sell at all — if you're open to it, I'd be glad to send over a "
        f"short example so you can see how it'd work for {name}.\n\n"
        "Either way, keep up the great work.\n\n"
        f"Best,\n{sender or DEFAULT_SENDER}"
    )
    return {"subject": subject, "body": body}
