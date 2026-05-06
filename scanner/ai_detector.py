from __future__ import annotations

import json
import os
from typing import Callable, Optional

from scanner.detector import Newsletter

LogCallback = Callable[[str], None]

_VALID_LABELS = {"newsletter", "spam", "phishing"}
_SEVERITY = {"phishing": 2, "spam": 1, "newsletter": 0}
_LABEL_COLOR = {"newsletter": "green", "spam": "yellow", "phishing": "red"}


def _sanitize(text: str) -> str:
    """Strip control characters (except newline/tab) that can corrupt API requests."""
    return "".join(ch for ch in text if ch >= " " or ch in "\n\t").strip()


def detect_provider() -> tuple[str, str] | None:
    """Return (provider_name, api_key) for the provider to use."""
    from auth.api_keys import PROVIDERS, get_selected_provider
    selected_slug = get_selected_provider()
    if selected_slug:
        for slug, display_name, env_var in PROVIDERS:
            if slug == selected_slug:
                key = os.environ.get(env_var, "").strip()
                if key:
                    return display_name, key
    for _, display_name, env_var in PROVIDERS:
        key = os.environ.get(env_var, "").strip()
        if key:
            return display_name, key
    return None


# ── Prompts ───────────────────────────────────────────────────────────────────

def _build_header_prompt(headers: dict) -> str:
    """Build a classification prompt from raw Gmail message headers."""
    from_h      = _sanitize(headers.get("from", "(unknown)"))
    subject     = _sanitize(headers.get("subject", "(none)"))
    list_unsub  = _sanitize(headers.get("list-unsubscribe", "")) or "not present"
    list_id     = _sanitize(headers.get("list-id", "")) or "not present"
    precedence  = _sanitize(headers.get("precedence", "")) or "not present"
    x_mailer    = _sanitize(headers.get("x-mailer", "")) or "not present"
    x_campaign  = _sanitize(headers.get("x-campaign", "")) or "not present"
    return (
        "You are an email classification assistant. Your ONLY task is to analyze the email "
        "headers below and output a single JSON object. Do not explain, do not ask questions, "
        "do not add any text outside the JSON.\n\n"
        f"From: {from_h}\n"
        f"Subject: {subject}\n"
        f"List-Unsubscribe: {list_unsub}\n"
        f"List-Id: {list_id}\n"
        f"Precedence: {precedence}\n"
        f"X-Mailer: {x_mailer}\n"
        f"X-Campaign: {x_campaign}\n\n"
        "Classify as exactly one of:\n"
        '  "newsletter" — legitimate subscription/marketing from a real brand\n'
        '  "spam"       — unsolicited bulk mail or low-quality promotions\n'
        '  "phishing"   — impersonation, scam, credential harvesting, or spoofed domain\n\n'
        'Output format (JSON only, no markdown, no extra text):\n'
        '{"label": "newsletter|spam|phishing", "reason": "one sentence"}'
    )


def _parse_json(raw: str) -> tuple[str, str]:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data = json.loads(raw)
    label = data.get("label", "newsletter")
    if label not in _VALID_LABELS:
        label = "newsletter"
    return label, data.get("reason", "")


# ── Per-provider raw callers (accept a prompt string) ─────────────────────────

def _call_anthropic(prompt: str, api_key: str) -> tuple[str, str]:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic")
    from auth.api_keys import get_model
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=get_model("anthropic"),
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(msg.content[0].text.strip())


def _call_openai(prompt: str, api_key: str) -> tuple[str, str]:
    try:
        import openai
    except ImportError:
        raise ImportError("Run: pip install openai")
    from auth.api_keys import get_model
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=get_model("openai"),
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(resp.choices[0].message.content.strip())


def _call_google(prompt: str, api_key: str) -> tuple[str, str]:
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("Run: pip install google-generativeai")
    from auth.api_keys import get_model
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(get_model("google"))
    resp = model.generate_content(prompt)
    return _parse_json(resp.text.strip())


_CALLERS = {
    "Anthropic (Claude)": _call_anthropic,
    "OpenAI (GPT)":       _call_openai,
    "Google (Gemini)":    _call_google,
}


# ── Connection testers (no token cost) ───────────────────────────────────────

def _test_anthropic(api_key: str) -> None:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic")
    anthropic.Anthropic(api_key=api_key).models.list()


def _test_openai(api_key: str) -> None:
    try:
        import openai
    except ImportError:
        raise ImportError("Run: pip install openai")
    list(openai.OpenAI(api_key=api_key).models.list())


def _test_google(api_key: str) -> None:
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("Run: pip install google-generativeai")
    genai.configure(api_key=api_key)
    next(iter(genai.list_models()))


_TESTERS = {
    "Anthropic (Claude)": _test_anthropic,
    "OpenAI (GPT)":       _test_openai,
    "Google (Gemini)":    _test_google,
}


def validate_provider() -> tuple[bool, str]:
    provider = detect_provider()
    if provider is None:
        return False, "No API key found. Add one in Manage API Keys."
    provider_name, api_key = provider
    try:
        _TESTERS[provider_name](api_key)
        return True, provider_name
    except Exception as exc:
        short = str(exc).split("\n")[0][:120]
        return False, f"{provider_name}: {short}"


def validate_specific(provider_name: str, api_key: str) -> tuple[bool, str]:
    if not api_key.strip():
        return False, f"No API key entered for {provider_name}"
    tester = _TESTERS.get(provider_name)
    if tester is None:
        return False, f"Unknown provider: {provider_name}"
    try:
        tester(api_key.strip())
        return True, provider_name
    except Exception as exc:
        short = str(exc).split("\n")[0][:120]
        return False, f"{provider_name}: {short}"


# ── Public API ────────────────────────────────────────────────────────────────

def classify_messages(
    messages: list[dict],
    log: Optional[LogCallback] = None,
) -> dict[str, tuple[str, str]]:
    """
    Classify each Gmail message individually by its headers.
    Each email is analyzed independently — no grouping by sender.
    Aggregates worst label (phishing > spam > newsletter) per sender domain.
    Returns {domain: (label, reason)}.
    """
    from scanner.detector import _extract_headers, _parse_sender

    provider = detect_provider()
    if provider is None:
        raise ValueError(
            "No AI API key found. Set one of:\n"
            "  ANTHROPIC_API_KEY  (Anthropic / Claude)\n"
            "  OPENAI_API_KEY     (OpenAI / GPT)\n"
            "  GOOGLE_API_KEY     (Google / Gemini)"
        )

    provider_name, api_key = provider
    caller = _CALLERS[provider_name]
    total = len(messages)
    domain_results: dict[str, tuple[str, str]] = {}

    if log:
        from auth.api_keys import PROVIDERS as _P, get_model as _gm
        slug = next((s for s, n, _ in _P if n == provider_name), "")
        model_id = _gm(slug) if slug else "unknown"
        log(f"[bold cyan]Provider: {provider_name}[/bold cyan]  [dim]({model_id})[/dim]")
        log(f"Analyzing {total} email{'s' if total != 1 else ''} individually…")

    for i, msg in enumerate(messages, 1):
        headers = _extract_headers(msg)
        from_h = headers.get("from", "")
        subject = _sanitize(headers.get("subject", ""))
        _, _, domain = _parse_sender(from_h) if from_h else ("", "", "unknown")

        if log:
            sender_display = _sanitize(from_h[:55]) if from_h else "(no sender)"
            subj_display = f"  [dim]{subject[:40]}[/dim]" if subject else ""
            log(f"[dim]{i}/{total}[/dim]  {sender_display}{subj_display}")

        try:
            label, reason = caller(_build_header_prompt(headers), api_key)

            current = domain_results.get(domain)
            if current is None or _SEVERITY.get(label, 0) > _SEVERITY.get(current[0], 0):
                domain_results[domain] = (label, reason)

            if log:
                color = _LABEL_COLOR.get(label, "green")
                log(f"  [{color}]→ {label}[/{color}]  [dim]{reason}[/dim]")
        except Exception as exc:
            if log:
                log(f"  [yellow]→ could not classify ({str(exc)[:200]})[/yellow]")

    if log:
        log("[bold cyan]── Classification complete ──[/bold cyan]")

    return domain_results
