from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Literal

import httpx

from scanner.detector import Newsletter

UnsubResult = Literal["success", "failed", "manual_required"]


async def unsubscribe(newsletter: Newsletter, gmail_service) -> tuple[UnsubResult, str]:
    """
    Try every available method in priority order.
    Returns (result, human-readable message).
    """
    # 1. RFC 8058 one-click POST — most reliable, preferred by Gmail/Yahoo
    if newsletter.one_click_post and newsletter.unsubscribe_url:
        result, msg = await _one_click_post(newsletter.unsubscribe_url)
        if result == "success":
            return result, msg

    # 2. Plain HTTPS GET (older newsletters)
    if newsletter.unsubscribe_url:
        result, msg = await _https_get(newsletter.unsubscribe_url)
        if result == "success":
            return result, msg

    # 3. mailto: — send a blank unsubscribe email via Gmail API
    if newsletter.unsubscribe_mailto:
        result, msg = _send_mailto(newsletter.unsubscribe_mailto, gmail_service)
        if result == "success":
            return result, msg

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
        if resp.status_code < 400:
            return "success", "Unsubscribed (via link)"
        return "failed", f"Server returned {resp.status_code}"
    except Exception as exc:
        return "failed", str(exc)


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
