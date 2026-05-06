from __future__ import annotations

import json
import os
from typing import Callable, Optional

from scanner.detector import Newsletter

LogCallback = Callable[[str], None]

_VALID_LABELS = {"newsletter", "spam", "phishing"}

def detect_provider() -> tuple[str, str] | None:
    """Return (provider_name, api_key) for the provider to use.
    Checks the user's explicit selection first, then falls back to priority order."""
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


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_prompt(nl: Newsletter) -> str:
    subjects = "\n".join(f"  - {s}" for s in nl.sample_subjects) if nl.sample_subjects else "  (none)"
    return (
        f"Classify this email sender as exactly one of: newsletter, spam, or phishing.\n\n"
        f"Sender name: {nl.sender_name}\n"
        f"Sender email: {nl.sender_email}\n"
        f"Domain: {nl.domain}\n"
        f"Emails received (last 90 days): {nl.email_count}\n"
        f"Sample subject lines:\n{subjects}\n\n"
        f"Definitions:\n"
        f'  "newsletter" — legitimate subscription or marketing email from a real brand\n'
        f'  "spam"       — unsolicited bulk mail, dubious promotions, low-quality marketing\n'
        f'  "phishing"   — impersonation, scam, credential harvesting, suspicious or spoofed domain\n\n'
        f'Respond with JSON only, no markdown: {{"label": "...", "reason": "one sentence"}}'
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
    """
    Check that a provider key is set and can authenticate (no token cost).
    Returns (success, message).
    """
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
    """
    Test a specific provider with the given key directly — no env var lookup.
    Returns (success, message).
    """
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


# ── Per-provider classifiers ──────────────────────────────────────────────────

def _classify_anthropic(nl: Newsletter, api_key: str) -> tuple[str, str]:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic")
    from auth.api_keys import get_model
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=get_model("anthropic"),
        max_tokens=120,
        messages=[{"role": "user", "content": _build_prompt(nl)}],
    )
    return _parse_json(msg.content[0].text.strip())


def _classify_openai(nl: Newsletter, api_key: str) -> tuple[str, str]:
    try:
        import openai
    except ImportError:
        raise ImportError("Run: pip install openai")
    from auth.api_keys import get_model
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=get_model("openai"),
        max_tokens=120,
        messages=[{"role": "user", "content": _build_prompt(nl)}],
    )
    return _parse_json(resp.choices[0].message.content.strip())


def _classify_google(nl: Newsletter, api_key: str) -> tuple[str, str]:
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("Run: pip install google-generativeai")
    from auth.api_keys import get_model
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(get_model("google"))
    resp = model.generate_content(_build_prompt(nl))
    return _parse_json(resp.text.strip())


_CLASSIFIERS = {
    "Anthropic (Claude)": _classify_anthropic,
    "OpenAI (GPT)":       _classify_openai,
    "Google (Gemini)":    _classify_google,
}


# ── Public API ────────────────────────────────────────────────────────────────

def classify_newsletters(
    newsletters: list[Newsletter],
    log: Optional[LogCallback] = None,
) -> list[Newsletter]:
    """
    Classify each Newsletter using the first available AI provider.
    Priority: Anthropic → OpenAI → Google.
    Updates .label and .label_reason in place. Returns the same list.
    Raises ValueError if no API key is found.
    """
    provider = detect_provider()
    if provider is None:
        raise ValueError(
            "No AI API key found. Set one of:\n"
            "  ANTHROPIC_API_KEY  (Anthropic / Claude)\n"
            "  OPENAI_API_KEY     (OpenAI / GPT)\n"
            "  GOOGLE_API_KEY     (Google / Gemini)"
        )

    provider_name, api_key = provider
    classifier = _CLASSIFIERS[provider_name]
    total = len(newsletters)

    _LABEL_COLOR = {"newsletter": "green", "spam": "yellow", "phishing": "red"}

    if log:
        from auth.api_keys import PROVIDERS as _P, get_model as _gm
        slug = next((s for s, n, _ in _P if n == provider_name), "")
        model_id = _gm(slug) if slug else "unknown"
        log(f"[bold cyan]Provider: {provider_name}[/bold cyan]  [dim]({model_id})[/dim]")
        log(f"Checking {total} sender{'s' if total != 1 else ''} for phishing & spam…")

    for i, nl in enumerate(newsletters, 1):
        if log:
            log(f"[dim]{i}/{total}[/dim]  {nl.sender_name}  [dim]{nl.sender_email}[/dim]")
        try:
            nl.label, nl.label_reason = classifier(nl, api_key)
            if log:
                color = _LABEL_COLOR.get(nl.label, "green")
                label_display = "phishing email" if nl.label == "phishing" else nl.label
                reason = f"  [dim]{nl.label_reason}[/dim]" if nl.label_reason else ""
                log(f"  [{color}]→ {label_display}[/{color}]{reason}")
        except Exception as exc:
            if log:
                log(f"  [dim]→ could not classify ({str(exc)[:60]})[/dim]")

    if log:
        log("[bold cyan]── Classification complete ──[/bold cyan]")

    return newsletters
