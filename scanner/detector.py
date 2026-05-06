from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Newsletter:
    sender_name: str
    sender_email: str
    domain: str
    email_count: int
    last_received: str          # raw Date header string, shown as-is
    unsubscribe_mailto: Optional[str] = None
    unsubscribe_url: Optional[str] = None
    one_click_post: bool = False
    label: str = "newsletter"   # "newsletter" | "spam" | "phishing"
    label_reason: str = ""
    sample_subjects: list[str] = field(default_factory=list)

    @property
    def can_auto_unsubscribe(self) -> bool:
        return bool(self.unsubscribe_mailto or self.unsubscribe_url)

    @property
    def method_label(self) -> str:
        if self.one_click_post and self.unsubscribe_url:
            return "One-click"
        if self.unsubscribe_url:
            return "Via link"
        if self.unsubscribe_mailto:
            return "Via email"
        return "Manual"


# ── Header helpers ────────────────────────────────────────────────────────────

def _extract_headers(message: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for h in message.get("payload", {}).get("headers", []):
        headers[h["name"].lower()] = h["value"]
    return headers


def _parse_unsubscribe_header(value: str) -> tuple[Optional[str], Optional[str]]:
    """Return (mailto_uri, https_url) from a List-Unsubscribe header value."""
    mailto: Optional[str] = None
    url: Optional[str] = None
    for part in re.findall(r"<([^>]+)>", value):
        if part.lower().startswith("mailto:") and mailto is None:
            mailto = part
        elif part.lower().startswith("http") and url is None:
            url = part
    return mailto, url


def _parse_sender(from_header: str) -> tuple[str, str, str]:
    """Return (display_name, email_address, domain)."""
    m = re.match(r'^"?([^"<]*)"?\s*<?([^>\s]+)>?$', from_header.strip())
    if m:
        name = m.group(1).strip().strip('"')
        email = m.group(2).strip()
    else:
        name = ""
        email = from_header.strip()

    domain = email.split("@")[-1].lower() if "@" in email else email.lower()
    if not name:
        name = domain.split(".")[0].title()

    return name, email, domain


# ── Newsletter scoring ────────────────────────────────────────────────────────

_NEWSLETTER_FROM_PATTERNS = re.compile(
    r"(noreply|no-reply|newsletter|news@|digest|weekly|daily|update|hello@|hi@|mailer|campaign)",
    re.IGNORECASE,
)


def _newsletter_score(headers: dict[str, str]) -> int:
    score = 0
    if "list-unsubscribe" in headers:
        score += 3
    if "list-id" in headers:
        score += 2
    if headers.get("precedence", "").lower() in ("bulk", "list", "junk"):
        score += 2
    if "x-campaign" in headers or "x-mailer" in headers:
        score += 1
    if _NEWSLETTER_FROM_PATTERNS.search(headers.get("from", "")):
        score += 1
    return score


def _is_newsletter(headers: dict[str, str]) -> bool:
    return _newsletter_score(headers) >= 2


# ── Public API ────────────────────────────────────────────────────────────────

def detect_newsletters(messages: list[dict]) -> list[Newsletter]:
    """
    Given a list of raw Gmail message objects, return grouped Newsletter objects
    sorted by email count (most frequent first).
    """
    groups: dict[str, dict] = {}

    for msg in messages:
        headers = _extract_headers(msg)

        if not _is_newsletter(headers):
            continue

        from_header = headers.get("from", "")
        if not from_header:
            continue

        name, email, domain = _parse_sender(from_header)
        date = headers.get("date", "")
        subject = headers.get("subject", "")

        mailto, url = None, None
        unsub_val = headers.get("list-unsubscribe", "")
        if unsub_val:
            mailto, url = _parse_unsubscribe_header(unsub_val)

        one_click = "list-unsubscribe-post" in headers

        if domain not in groups:
            groups[domain] = {
                "sender_name": name,
                "sender_email": email,
                "domain": domain,
                "count": 1,
                "last_received": date,
                "unsubscribe_mailto": mailto,
                "unsubscribe_url": url,
                "one_click_post": one_click,
                "sample_subjects": [subject] if subject else [],
            }
        else:
            g = groups[domain]
            g["count"] += 1
            # keep first non-empty unsubscribe info we find
            if not g["unsubscribe_mailto"] and mailto:
                g["unsubscribe_mailto"] = mailto
            if not g["unsubscribe_url"] and url:
                g["unsubscribe_url"] = url
            if one_click:
                g["one_click_post"] = True
            if subject and len(g["sample_subjects"]) < 3:
                g["sample_subjects"].append(subject)

    return sorted(
        [
            Newsletter(
                sender_name=g["sender_name"],
                sender_email=g["sender_email"],
                domain=g["domain"],
                email_count=g["count"],
                last_received=g["last_received"],
                unsubscribe_mailto=g["unsubscribe_mailto"],
                unsubscribe_url=g["unsubscribe_url"],
                one_click_post=g["one_click_post"],
                sample_subjects=g["sample_subjects"],
            )
            for g in groups.values()
        ],
        key=lambda n: n.email_count,
        reverse=True,
    )


def group_remaining(messages: list[dict], exclude_domains: set[str]) -> list[Newsletter]:
    """
    Group messages from senders NOT in exclude_domains.
    Only includes senders with 2+ emails — one-off contacts are skipped.
    Returns Newsletter objects for AI threat analysis (no unsubscribe info).
    """
    groups: dict[str, dict] = {}

    for msg in messages:
        headers = _extract_headers(msg)
        from_header = headers.get("from", "")
        if not from_header:
            continue
        name, email, domain = _parse_sender(from_header)
        if domain in exclude_domains:
            continue
        subject = headers.get("subject", "")
        date = headers.get("date", "")

        if domain not in groups:
            groups[domain] = {
                "sender_name": name,
                "sender_email": email,
                "domain": domain,
                "count": 1,
                "last_received": date,
                "sample_subjects": [subject] if subject else [],
            }
        else:
            g = groups[domain]
            g["count"] += 1
            if subject and len(g["sample_subjects"]) < 3:
                g["sample_subjects"].append(subject)

    return sorted(
        [
            Newsletter(
                sender_name=g["sender_name"],
                sender_email=g["sender_email"],
                domain=g["domain"],
                email_count=g["count"],
                last_received=g["last_received"],
                sample_subjects=g["sample_subjects"],
            )
            for g in groups.values()
            if g["count"] >= 2
        ],
        key=lambda n: n.email_count,
        reverse=True,
    )
