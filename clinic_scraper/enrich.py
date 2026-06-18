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

# Instagram URL path segments that are NOT usernames (posts, reels, etc.).
INSTAGRAM_RESERVED = {
    "p", "reel", "reels", "explore", "stories", "tv", "accounts", "about",
    "developer", "legal", "directory", "web", "sharer", "share", "embed",
    "invites", "challenge", "session", "emails", "ads",
}
# Valid IG handles: letters, digits, dot, underscore, up to 30 chars.
_IG_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")

# Handles that belong to website builders / platforms, not the clinic — these
# leak in from "Made with Wix" style footer links.
INSTAGRAM_HANDLE_BLOCKLIST = {
    "wix", "wixcom", "squarespace", "godaddy", "wordpress", "wordpressdotcom",
    "weebly", "shopify", "linktree", "canva", "mailchimp", "vistaprint",
    "fresha", "treatwell", "instagram", "facebook", "tiktok", "youtube",
    "google", "explore", "share",
}


def instagram_handle(value: str) -> Optional[str]:
    """Extract a clean Instagram username from a URL or raw handle.

    Returns the bare handle (no @, lowercased) or None if it's not a real
    profile link (e.g. a /p/ post, /reel/, or share link).
    """
    if not value:
        return None
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]

    # If it looks like a URL, take the first path segment; else use as-is.
    if "/" in value or "instagram.com" in value:
        path = urlparse(value if "//" in value else "//" + value).path
        segments = [s for s in path.split("/") if s]
        if not segments:
            return None
        candidate = segments[0]
    else:
        candidate = value

    candidate = candidate.split("?")[0].lower()
    if candidate in INSTAGRAM_RESERVED or candidate in INSTAGRAM_HANDLE_BLOCKLIST:
        return None
    if not _IG_HANDLE_RE.match(candidate):
        return None
    return candidate


def normalize_instagram(value: str) -> tuple[str, str]:
    """Return (clean_profile_url, "@handle") or ("", "") if not a real profile."""
    handle = instagram_handle(value)
    if not handle:
        return "", ""
    return f"https://www.instagram.com/{handle}", f"@{handle}"


def finalize_socials(lead: Lead) -> Lead:
    """Clean a lead's Instagram into a canonical URL + @handle (in place)."""
    url, handle = normalize_instagram(lead.instagram)
    lead.instagram = url
    lead.instagram_handle = handle
    return lead

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
        full = urljoin(base_url, a["href"])
        host = urlparse(full).netloc.lower()
        for platform, hosts in SOCIAL_HOSTS.items():
            if found[platform] or not any(h in host for h in hosts):
                continue
            # For Instagram, only accept real profile links (skip /p/, /reel/…).
            if platform == "instagram" and not instagram_handle(full):
                continue
            found[platform] = full.split("?")[0]

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
