from __future__ import annotations

import base64
import re
from email.mime.text import MIMEText
from typing import Callable, Literal, Optional

import httpx

from scanner.detector import Newsletter

LogCallback = Callable[[str], None]

_SUCCESS_RE = re.compile(
    r"(successfully\s+unsubscribed|you.ve been (removed|unsubscribed)|"
    r"opted[\s\-]out|no longer (receive|get)|unsubscription\s+confirmed|"
    r"removed from|you are (now\s+)?unsubscribed|has been removed)",
    re.IGNORECASE,
)

_CONFIRM_RE = re.compile(
    r"(click (here|to confirm|the (button|link))|please confirm|"
    r"confirm (your|the) unsubscri|to (complete|finish) your unsubscri)",
    re.IGNORECASE,
)

UnsubResult = Literal["success", "failed", "manual_required"]


async def unsubscribe(
    newsletter: Newsletter,
    gmail_service,
    log: Optional[LogCallback] = None,
) -> tuple[UnsubResult, str]:
    """
    Try every available method in priority order.
    Returns (result, human-readable message).
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    # 1. RFC 8058 one-click POST — most reliable, preferred by Gmail/Yahoo
    if newsletter.one_click_post and newsletter.unsubscribe_url:
        _log("Trying one-click POST (RFC 8058)…")
        result, msg = await _one_click_post(newsletter.unsubscribe_url)
        if result == "success":
            _log(f"✓ {msg}")
            return result, msg
        _log(f"✗ {msg} — trying next method…")

    # 2. Plain HTTPS GET (older newsletters)
    if newsletter.unsubscribe_url:
        _log("Trying HTTPS GET…")
        result, msg = await _https_get(newsletter.unsubscribe_url)
        if result == "success":
            _log(f"✓ {msg}")
            return result, msg
        _log(f"✗ {msg}")

    # 3. mailto: — send a blank unsubscribe email via Gmail API
    if newsletter.unsubscribe_mailto:
        address = newsletter.unsubscribe_mailto.replace("mailto:", "").split("?")[0].strip()
        _log(f"Sending unsubscribe email to {address}…")
        result, msg = _send_mailto(newsletter.unsubscribe_mailto, gmail_service)
        if result == "success":
            _log(f"✓ {msg}")
            return result, msg
        _log(f"✗ {msg}")

    _log("No automatic method succeeded — manual action required")
    return "manual_required", "No automatic method found — open the email and click Unsubscribe manually."


# ── Private helpers ───────────────────────────────────────────────────────────

async def _one_click_post(url: str) -> tuple[UnsubResult, str]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.post(
                url,
                data={"List-Unsubscribe": "One-Click"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code < 400:
            return "success", "Unsubscribed (one-click)"
        return "failed", f"Server returned {resp.status_code}"
    except Exception as exc:
        return "failed", str(exc)


async def _https_get(url: str) -> tuple[UnsubResult, str]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return "failed", f"Server returned {resp.status_code}"

        body = resp.text
        # Page explicitly confirms unsubscribe succeeded
        if _SUCCESS_RE.search(body):
            return "success", "Unsubscribed (via link)"
        # Page has a confirmation form or asks user to click — GET alone isn't enough
        if _CONFIRM_RE.search(body) or ("<form" in body.lower() and "unsubscrib" in body.lower()):
            return "failed", "Unsubscribe page requires manual confirmation"
        # Short / redirect response with no form — likely auto-processed
        if len(body) < 5000:
            return "success", "Unsubscribed (via link)"
        # Long page with no clear success message — fall through to mailto
        return "failed", "Could not confirm unsubscribe — no success message in response"
    except Exception as exc:
        return "failed", str(exc)


def delete_newsletter_emails(
    domain: str,
    gmail_service,
    max_emails: int = 500,
    log: Optional[LogCallback] = None,
) -> int:
    """
    Move all emails from a sender domain to Trash.
    Returns the number of emails trashed.
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    query = f"from:@{domain}"
    trashed = 0
    page_token = None
    _log(f"Searching inbox for emails from @{domain}…")

    while trashed < max_emails:
        params: dict = {"userId": "me", "q": query, "maxResults": min(100, max_emails - trashed)}
        if page_token:
            params["pageToken"] = page_token

        result = gmail_service.users().messages().list(**params).execute()
        messages = result.get("messages", [])
        if not messages:
            _log("No more emails found")
            break

        _log(f"Moving {len(messages)} email(s) to trash…")
        for msg in messages:
            gmail_service.users().messages().trash(userId="me", id=msg["id"]).execute()
            trashed += 1

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    _log(f"✓ {trashed} email(s) moved to trash")
    return trashed


def check_inbox_count(domain: str, gmail_service) -> int:
    """Return number of inbox emails from domain. Returns -1 on API error."""
    try:
        query = f"from:@{domain} in:inbox"
        result = gmail_service.users().messages().list(
            userId="me", q=query, maxResults=100
        ).execute()
        return len(result.get("messages", []))
    except Exception:
        return -1


def _send_mailto(mailto_uri: str, gmail_service) -> tuple[UnsubResult, str]:
    # Strip "mailto:" and any query string (e.g. ?subject=unsubscribe)
    address = mailto_uri.replace("mailto:", "").split("?")[0].strip()

    try:
        msg = MIMEText("")
        msg["To"] = address
        msg["Subject"] = "Unsubscribe"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail_service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return "success", f"Unsubscribe email sent to {address}"
    except Exception as exc:
        return "failed", str(exc)
