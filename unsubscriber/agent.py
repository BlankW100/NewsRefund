"""
unsubscriber/agent.py — Hybrid Unsubscribe & Block Fallback pipeline
=====================================================================

Phase 1  Header fast path     List-Unsubscribe header  → httpx POST/GET/mailto
Phase 2  Scrape path           fetch email body         → BS4 link  → httpx GET
Phase 3  Stubborn path         JS-heavy page            → Playwright click
Phase 4  Nuclear fallback      Gmail settings filter    → auto-trash future mail
         (also taken immediately when sender is phishing)
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import re
import urllib.parse
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Callable, Optional

import httpx
from bs4 import BeautifulSoup

from scanner.detector import Newsletter

LogCallback = Callable[[str], None]

# ── Shared regex patterns ─────────────────────────────────────────────────────

_SUCCESS_RE = re.compile(
    r"(successfully\s+unsubscribed|you.ve been (removed|unsubscribed)|"
    r"opted[\s\-]out|no longer (receive|get)|unsubscription\s+confirmed|"
    r"removed from|you are (now\s+)?unsubscribed|has been removed)",
    re.IGNORECASE,
)
_CONFIRM_FORM_RE = re.compile(
    r"(click (here|to confirm|the (button|link))|please confirm|"
    r"confirm (your|the) unsubscri|to (complete|finish) your unsubscri)",
    re.IGNORECASE,
)
_UNSUB_KEYWORD_RE = re.compile(
    r"unsubscribe|opt.?out|remove me|manage.*preferences|email.*preferences",
    re.I,
)
_PLAYWRIGHT_CONFIRM_RE = re.compile(
    r"you.ve been unsubscribed|successfully removed|confirmed|opt.?out complete",
    re.I,
)


def _safe_to_fetch(url: str) -> bool:
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if not u.hostname:
        return False
    try:
        ip = ipaddress.ip_address(u.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        if u.hostname in ("localhost",) or u.hostname.endswith(".local"):
            return False
    return True


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    phase: int    # 1–4 (which phase resolved it); 0 = all phases exhausted + failed
    success: bool
    method: str   # e.g. "one-click-post", "scrape-get", "playwright-click", "gmail-filter"
    message: str

    @property
    def phase_label(self) -> str:
        return {
            0: "All phases failed",
            1: "Header",
            2: "Body scrape",
            3: "Playwright",
            4: "Gmail block",
        }.get(self.phase, f"Phase {self.phase}")


# ── Main agent ────────────────────────────────────────────────────────────────

class UnsubscribeAgent:
    """
    Execute the 4-phase hybrid unsubscribe/block pipeline for a single sender.

    Usage::

        agent = UnsubscribeAgent(newsletter, gmail_service, log=my_log_fn)
        result = await agent.run()
        # result.success, result.phase_label, result.message
    """

    def __init__(
        self,
        newsletter: Newsletter,
        gmail_service,
        *,
        force_block: bool = False,
        log: Optional[LogCallback] = None,
    ) -> None:
        self.nl = newsletter
        self._svc = gmail_service
        self._force_block = force_block
        self._log: LogCallback = log or (lambda _: None)

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self) -> AgentResult:
        if self._force_block:
            self._log(
                f"[yellow]⚠  {self.nl.sender_name} flagged as phishing — "
                "jumping directly to Gmail block[/yellow]"
            )
            return await self._phase4_gmail_block()

        # Phase 1 — try what the header already tells us
        result = await self._phase1_header()
        if result.success:
            return result

        # Phase 2 — fetch body, parse link, try httpx; returns URL for Phase 3 if JS needed
        playwright_url, result = await self._phase2_scrape()
        if result.success:
            return result

        # Phase 3 — only reached when Phase 2 found a URL that needs JavaScript
        if playwright_url:
            result = await self._phase3_playwright(playwright_url)
            if result.success:
                return result

        # Phase 4 — nuclear: Gmail filter → TRASH
        self._log("[yellow]All unsubscribe methods exhausted — activating Gmail block[/yellow]")
        return await self._phase4_gmail_block()

    # ── Phase 1: Header fast path ─────────────────────────────────────────────

    async def _phase1_header(self) -> AgentResult:
        nl = self.nl

        if nl.one_click_post and nl.unsubscribe_url:
            self._log(f"[Phase 1] One-click POST → {nl.unsubscribe_url}")
            ok, msg = await self._http_post_one_click(nl.unsubscribe_url)
            if ok:
                return AgentResult(1, True, "one-click-post", msg)
            self._log(f"[Phase 1] ✗ {msg}")

        if nl.unsubscribe_url:
            self._log(f"[Phase 1] HTTPS GET → {nl.unsubscribe_url}")
            ok, msg = await self._http_get(nl.unsubscribe_url)
            if ok:
                return AgentResult(1, True, "https-get", msg)
            self._log(f"[Phase 1] ✗ {msg}")

        if nl.unsubscribe_mailto:
            self._log(f"[Phase 1] mailto: → {nl.unsubscribe_mailto}")
            ok, msg = await asyncio.get_event_loop().run_in_executor(
                None, self._send_mailto_sync, nl.unsubscribe_mailto
            )
            if ok:
                return AgentResult(1, True, "mailto", msg)
            self._log(f"[Phase 1] ✗ {msg}")

        self._log("[Phase 1] No header method succeeded — escalating")
        return AgentResult(1, False, "header", "No List-Unsubscribe header or all attempts failed")

    # ── Phase 2: Body scrape path ─────────────────────────────────────────────

    async def _phase2_scrape(self) -> tuple[Optional[str], AgentResult]:
        """
        Returns (playwright_fallback_url | None, result).
        playwright_fallback_url is set only when a link was found but GET failed
        (indicating JS interaction is probably required).
        """
        self._log("[Phase 2] Fetching email body for scraping…")
        html = await asyncio.get_event_loop().run_in_executor(
            None, self._fetch_body_sync
        )
        if not html:
            self._log("[Phase 2] Could not retrieve email body")
            return None, AgentResult(2, False, "scrape", "Could not fetch email body")

        url = self._extract_unsub_link(html)
        if not url:
            self._log("[Phase 2] No unsubscribe link found in body")
            return None, AgentResult(2, False, "scrape", "No unsubscribe link found in body")

        self._log(f"[Phase 2] Found link: {url}")
        ok, msg = await self._http_get(url)
        if ok:
            return None, AgentResult(2, True, "scrape-get", msg)

        self._log(f"[Phase 2] GET failed ({msg}) — handing to Playwright")
        return url, AgentResult(2, False, "scrape", f"Link found but GET failed: {msg}")

    def _fetch_body_sync(self) -> Optional[str]:
        """Blocking: fetch the most recent email from this sender, return HTML body."""
        try:
            resp = self._svc.users().messages().list(
                userId="me",
                q=f"from:{self.nl.sender_email}",
                maxResults=1,
            ).execute()
            msgs = resp.get("messages", [])
            if not msgs:
                return None
            full = self._svc.users().messages().get(
                userId="me",
                messageId=msgs[0]["id"],
                format="full",
            ).execute()
            return self._extract_html_from_payload(full.get("payload", {}))
        except Exception:
            return None

    def _extract_html_from_payload(self, payload: dict) -> Optional[str]:
        """Recursively find the first text/html body part in a Gmail payload."""
        if payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            result = self._extract_html_from_payload(part)
            if result:
                return result
        return None

    def _extract_unsub_link(self, html: str) -> Optional[str]:
        """Return the highest-scoring unsubscribe <a href> URL in the HTML."""
        soup = BeautifulSoup(html, "html.parser")
        best_url: Optional[str] = None
        best_score = 0
        for tag in soup.find_all("a", href=True):
            href: str = tag["href"].strip()
            if not href.startswith("http"):
                continue
            if not _safe_to_fetch(href):
                continue
            text = tag.get_text(strip=True)
            score = (
                (2 if _UNSUB_KEYWORD_RE.search(href) else 0)
                + (3 if _UNSUB_KEYWORD_RE.search(text) else 0)
            )
            if score > best_score:
                best_score, best_url = score, href
        return best_url if best_score > 0 else None

    # ── Phase 3: Playwright stubborn path ─────────────────────────────────────

    async def _phase3_playwright(self, url: str) -> AgentResult:
        if not _safe_to_fetch(url):
            return AgentResult(3, False, "playwright", f"Blocked unsafe URL: {url}")
        self._log(f"[Phase 3] Playwright → {url}")
        try:
            from playwright.async_api import async_playwright  # lazy import
        except ImportError:
            return AgentResult(3, False, "playwright", "playwright not installed")

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )
                page = await ctx.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                confirmed = await self._playwright_click_confirm(page)
                await browser.close()

            if confirmed:
                return AgentResult(3, True, "playwright-click", "Playwright confirmed unsubscribe")
            return AgentResult(3, False, "playwright", "Page loaded but no confirmation detected")
        except Exception as exc:
            self._log(f"[Phase 3] Error: {exc}")
            return AgentResult(3, False, "playwright", str(exc))

    async def _playwright_click_confirm(self, page) -> bool:
        """Try to click an unsubscribe/confirm element and detect success text."""
        body_text = await page.evaluate("() => document.body.innerText")
        if _PLAYWRIGHT_CONFIRM_RE.search(body_text):
            return True  # landing page already confirmed

        for selector in ("button", "a", "input[type=submit]"):
            for loc in await page.locator(selector).all():
                try:
                    text = (await loc.inner_text()).strip()
                except Exception:
                    continue
                if not _UNSUB_KEYWORD_RE.search(text):
                    continue
                try:
                    await loc.click()
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                    body_text = await page.evaluate("() => document.body.innerText")
                    if _PLAYWRIGHT_CONFIRM_RE.search(body_text):
                        return True
                except Exception:
                    continue
        return False

    # ── Phase 4: Gmail block filter ───────────────────────────────────────────

    async def _phase4_gmail_block(self) -> AgentResult:
        sender = self.nl.sender_email
        self._log(f"[Phase 4] Creating Gmail block filter for <{sender}>")
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._create_gmail_filter_sync, sender
            )
            return AgentResult(
                4, True, "gmail-filter",
                f"Gmail filter created — future mail from {sender} will be auto-trashed",
            )
        except Exception as exc:
            self._log(f"[Phase 4] Filter creation failed: {exc}")
            return AgentResult(4, False, "gmail-filter", str(exc))

    def _create_gmail_filter_sync(self, sender_email: str) -> None:
        """
        Blocking. Requires the gmail.settings.basic OAuth scope.
        If the current token lacks that scope the caller will receive an
        HttpError 403/invalid_scope — caught upstream and surfaced as a
        failed AgentResult with a clear re-auth hint.
        """
        try:
            self._svc.users().settings().filters().create(
                userId="me",
                body={
                    "criteria": {"from": sender_email},
                    "action": {
                        "addLabelIds": ["TRASH"],
                        "removeLabelIds": ["INBOX", "SPAM"],
                    },
                },
            ).execute()
        except Exception as exc:
            msg = str(exc)
            if "invalid_scope" in msg or "insufficientPermissions" in msg or "403" in msg:
                raise PermissionError(
                    "Gmail block requires re-authentication with extra permissions. "
                    "Log out (Ctrl+L) and log back in, then retry."
                ) from exc
            raise

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _looks_unsubscribed(self, body: str) -> tuple[bool, str | None]:
        if _SUCCESS_RE.search(body):
            return True, "confirmed via page content"
        if _CONFIRM_FORM_RE.search(body) or (
            "<form" in body.lower() and "unsubscrib" in body.lower()
        ):
            return False, "page requires manual confirmation"
        return False, None

    async def _http_post_one_click(self, url: str) -> tuple[bool, str]:
        if not _safe_to_fetch(url):
            return False, f"Blocked unsafe URL: {url}"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                r = await client.post(
                    url,
                    data={"List-Unsubscribe": "One-Click"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if not _safe_to_fetch(str(r.url)):
                return False, f"Redirect led to unsafe URL: {r.url}"
            if r.status_code >= 400:
                return False, f"POST returned {r.status_code}"
            ok, msg = self._looks_unsubscribed(r.text)
            if ok:
                return True, msg
            if msg:
                return False, msg
            return False, f"POST {r.status_code} — no confirmation marker; escalating"
        except Exception as exc:
            return False, str(exc)

    async def _http_get(self, url: str) -> tuple[bool, str]:
        if not _safe_to_fetch(url):
            return False, f"Blocked unsafe URL: {url}"
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                r = await client.get(url)
            if not _safe_to_fetch(str(r.url)):
                return False, f"Redirect led to unsafe URL: {r.url}"
            if r.status_code >= 400:
                return False, f"HTTP {r.status_code}"
            if _SUCCESS_RE.search(r.text):
                return True, f"Confirmed via page content (HTTP {r.status_code})"
            if _CONFIRM_FORM_RE.search(r.text) or (
                "<form" in r.text.lower() and "unsubscrib" in r.text.lower()
            ):
                return False, "Page requires manual confirmation (form/button)"
            return False, f"HTTP {r.status_code} — no confirmation marker found; escalating to Phase 3"
        except Exception as exc:
            return False, str(exc)

    def _send_mailto_sync(self, mailto_uri: str) -> tuple[bool, str]:
        """Blocking: send an unsubscribe email via the Gmail API."""
        parsed = urllib.parse.urlparse(mailto_uri)
        to_addr = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        subject = qs.get("subject", ["Unsubscribe"])[0]
        body_text = qs.get("body", ["Please unsubscribe me."])[0]
        try:
            msg = MIMEText(body_text)
            msg["To"] = to_addr
            msg["Subject"] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            self._svc.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return True, f"Unsubscribe email sent to {to_addr}"
        except Exception as exc:
            return False, str(exc)
