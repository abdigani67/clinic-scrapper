"""Enrich a lead by crawling its website for email and social links."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config
from .models import Lead

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Emails that are almost never real leads.
EMAIL_BLOCKLIST = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "domain.com",
    "email.com",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
)

SOCIAL_HOSTS = {
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "tiktok": ("tiktok.com",),
}

# Pages likely to hold contact details, tried in addition to the homepage.
CONTACT_PATHS = ("/contact", "/contact-us", "/about", "/book", "/booking")


def _clean_email(email: str) -> Optional[str]:
    email = email.strip().strip(".").lower()
    if any(bad in email for bad in EMAIL_BLOCKLIST):
        return None
    return email


def _fetch(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code == 200 and "text/html" in resp.headers.get(
            "Content-Type", ""
        ):
            return resp.text
    except requests.RequestException:
        return None
    return None


def _extract_from_html(html: str, base_url: str) -> dict:
    found = {"email": "", "instagram": "", "facebook": "", "tiktok": ""}
    soup = BeautifulSoup(html, "html.parser")

    # Emails: prefer explicit mailto: links, then fall back to page text.
    for a in soup.select('a[href^="mailto:"]'):
        candidate = _clean_email(a["href"].split("mailto:", 1)[-1].split("?")[0])
        if candidate:
            found["email"] = candidate
            break
    if not found["email"]:
        for match in EMAIL_RE.findall(html):
            candidate = _clean_email(match)
            if candidate:
                found["email"] = candidate
                break

    # Social links by host.
    for a in soup.find_all("a", href=True):
        host = urlparse(urljoin(base_url, a["href"])).netloc.lower()
        for platform, hosts in SOCIAL_HOSTS.items():
            if not found[platform] and any(h in host for h in hosts):
                found[platform] = urljoin(base_url, a["href"]).split("?")[0]

    return found


def enrich_lead(lead: Lead) -> Lead:
    """Populate email + social fields by crawling the lead's website in place."""
    if not lead.website:
        return lead

    base = lead.website
    pages = [base] + [urljoin(base, path) for path in CONTACT_PATHS]

    for url in pages:
        html = _fetch(url)
        if not html:
            continue
        data = _extract_from_html(html, base)
        lead.email = lead.email or data["email"]
        lead.instagram = lead.instagram or data["instagram"]
        lead.facebook = lead.facebook or data["facebook"]
        lead.tiktok = lead.tiktok or data["tiktok"]

        # Stop early once we have an email and at least one social profile.
        if lead.email and (lead.instagram or lead.facebook or lead.tiktok):
            break

    return lead
