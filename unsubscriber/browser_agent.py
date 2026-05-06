from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Callable, Optional

from scanner.detector import Newsletter

if TYPE_CHECKING:
    from playwright.async_api import Page

LogCallback = Callable[[str], None]

_SUCCESS_RE = re.compile(
    r"(successfully\s+unsubscribed|you.ve been (removed|unsubscribed)|"
    r"opted[\s\-]out|no longer (receive|get)|unsubscription\s+confirmed|"
    r"removed from|you are (now\s+)?unsubscribed|has been removed)",
    re.IGNORECASE,
)


async def browser_unsub(
    nl: Newsletter,
    gmail_service,
    log: Optional[LogCallback] = None,
) -> tuple[str, str]:
    """
    Unsubscribe using Playwright browser automation + AI page navigation.
    Falls back to mailto send if no URL is available.
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    if not nl.unsubscribe_url and nl.unsubscribe_mailto:
        from unsubscriber.handler import _send_mailto
        addr = nl.unsubscribe_mailto.replace("mailto:", "").split("?")[0].strip()
        _log(f"Sending unsubscribe email to {addr}…")
        result, msg = _send_mailto(nl.unsubscribe_mailto, gmail_service)
        _log(f"{'✓' if result == 'success' else '✗'} {msg}")
        return result, msg

    if not nl.unsubscribe_url:
        _log("No unsubscribe URL available — manual action required")
        return "manual_required", "No unsubscribe URL or mailto found"

    url = nl.unsubscribe_url
    _log(f"Opening: {url[:80]}{'…' if len(url) > 80 else ''}")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        _log("[yellow]Playwright not available — falling back to HTTP[/yellow]")
        from unsubscriber.handler import unsubscribe as _http_unsub
        return await _http_unsub(nl, gmail_service, log=log)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            except Exception as exc:
                _log(f"[yellow]Load warning: {str(exc)[:80]}[/yellow]")

            result, msg = await _navigate_and_unsub(page, nl, _log)
            await browser.close()
            return result, msg

    except Exception as exc:
        _log(f"[red]Browser error: {str(exc)[:100]}[/red]")
        return "failed", str(exc)[:100]


async def _navigate_and_unsub(page: Page, nl: Newsletter, log: LogCallback) -> tuple[str, str]:
    try:
        title = await page.title()
        log(f"Page: '{title}'")

        body = (await page.evaluate("() => document.body.innerText")).strip()

        if _SUCCESS_RE.search(body):
            log("[green]✓ Unsubscribe confirmation already on page[/green]")
            return "success", "Unsubscribed via browser"

        elems = await page.evaluate("""() => {
            const seen = new Set(), out = [];
            for (const sel of ['button','input[type="submit"]','input[type="button"]','a[href]']) {
                for (const el of document.querySelectorAll(sel)) {
                    const t = (el.innerText || el.value || '').trim().replace(/\\s+/g,' ');
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && t && !seen.has(t)) {
                        seen.add(t);
                        out.push({tag: el.tagName, text: t.slice(0, 80)});
                    }
                }
            }
            return out.slice(0, 25);
        }""")

        has_email_field = await page.evaluate(
            '() => !!document.querySelector(\'input[type="email"],input[name*="email" i]\')'
        )

        log("Asking AI what to click…")
        action = await _ask_ai(nl, title, body[:2000], elems, has_email_field)
        act = action.get("action", "heuristic")

        if act == "already_unsubscribed":
            log("[green]✓ Already unsubscribed[/green]")
            return "success", "Already unsubscribed"

        if act == "fill_and_submit" and has_email_field:
            fill_val = action.get("email_value") or ""
            if not fill_val:
                from auth.gmail import get_connected_email
                fill_val = get_connected_email() or nl.sender_email
            log(f"Filling email field: {fill_val}")
            try:
                await page.fill(
                    'input[type="email"],input[name*="email" i]',
                    fill_val,
                    timeout=4_000,
                )
            except Exception:
                pass

        click_text = action.get("click_text", "")
        if act in ("click", "fill_and_submit") and click_text:
            log(f"Clicking: '{click_text}'")
            try:
                loc = page.get_by_role("button", name=click_text, exact=False)
                if not await loc.count():
                    loc = page.get_by_text(click_text, exact=False).first
                await loc.click(timeout=6_000)
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                new_body = await page.evaluate("() => document.body.innerText")
                if _SUCCESS_RE.search(new_body):
                    log("[green]✓ Unsubscribe confirmed[/green]")
                else:
                    log("[dim]Clicked — no explicit confirmation, assuming success[/dim]")
                return "success", "Unsubscribed via browser"
            except Exception as exc:
                log(f"[yellow]Click failed: {str(exc)[:60]}[/yellow]")

        return await _heuristic_click(page, log)

    except Exception as exc:
        return "failed", str(exc)[:100]


async def _heuristic_click(page: Page, log: LogCallback) -> tuple[str, str]:
    for phrase in ["Unsubscribe", "Opt out", "Opt Out", "Remove me", "UNSUBSCRIBE"]:
        try:
            loc = page.get_by_text(phrase, exact=False)
            if await loc.count():
                log(f"Heuristic: clicking '{phrase}'")
                await loc.first.click(timeout=5_000)
                await page.wait_for_load_state("domcontentloaded", timeout=8_000)
                body = await page.evaluate("() => document.body.innerText")
                if _SUCCESS_RE.search(body):
                    log("[green]✓ Confirmed[/green]")
                return "success", "Unsubscribed via browser"
        except Exception:
            continue
    log("[yellow]Could not find unsubscribe button — manual action required[/yellow]")
    return "manual_required", "Unsubscribe button not found on page"


async def _ask_ai(
    nl: Newsletter,
    title: str,
    body: str,
    elems: list,
    has_email_field: bool,
) -> dict:
    from scanner.ai_detector import detect_provider
    provider = detect_provider()
    if not provider:
        return {"action": "heuristic"}

    provider_name, api_key = provider
    elem_lines = "\n".join(f"  [{e['tag']}] {e['text']}" for e in elems)
    prompt = (
        f"You are helping unsubscribe from: {nl.sender_name} <{nl.sender_email}>.\n"
        f"You are on their unsubscribe / manage-subscriptions page.\n\n"
        f"Page title: {title}\n"
        f"Page text (excerpt):\n{body}\n\n"
        f"Visible buttons and links:\n{elem_lines or '  (none found)'}\n"
        f"Has email input field: {has_email_field}\n\n"
        f"Pick exactly one action. Respond with JSON only, no markdown:\n"
        f'{{"action":"click","click_text":"<exact button or link text>"}}\n'
        f'{{"action":"fill_and_submit","email_value":"<email to enter>","click_text":"<submit button text>"}}\n'
        f'{{"action":"already_unsubscribed"}}\n'
        f'{{"action":"heuristic"}}\n'
    )

    def _sync_call() -> dict:
        try:
            raw = ""
            if provider_name == "Anthropic (Claude)":
                import anthropic
                from anthropic.types import TextBlock as _TextBlock
                from auth.api_keys import get_model
                c = anthropic.Anthropic(api_key=api_key)
                m = c.messages.create(
                    model=get_model("anthropic"), max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                block = m.content[0]
                raw = block.text.strip() if isinstance(block, _TextBlock) else ""
            elif provider_name == "OpenAI (GPT)":
                import openai
                from auth.api_keys import get_model
                c = openai.OpenAI(api_key=api_key)
                content = c.chat.completions.create(
                    model=get_model("openai"),
                    messages=[{"role": "user", "content": prompt}],
                ).choices[0].message.content
                raw = (content or "").strip()
            elif provider_name == "Google (Gemini)":
                from google.generativeai import configure as _cfg  # type: ignore[attr-defined]
                from google.generativeai import GenerativeModel as _GM  # type: ignore[attr-defined]
                from auth.api_keys import get_model
                _cfg(api_key=api_key)
                raw = (_GM(get_model("google")).generate_content(prompt).text or "").strip()
            elif provider_name == "Ollama (Local)":
                import httpx
                from auth.api_keys import get_model
                resp = httpx.post(
                    f"{api_key.rstrip('/')}/api/chat",
                    json={
                        "model": get_model("ollama"),
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                raw = resp.json()["message"]["content"].strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return json.loads(raw)
        except Exception:
            return {"action": "heuristic"}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_call)
