from __future__ import annotations

import json
import os
from pathlib import Path

_CONFIG_DIR = Path.home() / ".newsrefund"
_KEYS_FILE = _CONFIG_DIR / "api_keys.json"

# (slug, display name, env var) — priority order
PROVIDERS: list[tuple[str, str, str]] = [
    ("anthropic", "Anthropic (Claude)", "ANTHROPIC_API_KEY"),
    ("openai",    "OpenAI (GPT)",       "OPENAI_API_KEY"),
    ("google",    "Google (Gemini)",    "GOOGLE_API_KEY"),
    ("ollama",    "Ollama (Local)",     "OLLAMA_BASE_URL"),
]

# (display label, model id) per provider
PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    "anthropic": [
        ("Haiku 4.5  — fast & cheap",  "claude-haiku-4-5-20251001"),
        ("Sonnet 4.6 — balanced",      "claude-sonnet-4-6"),
        ("Opus 4.7   — most capable",  "claude-opus-4-7"),
    ],
    "openai": [
        ("GPT-4o mini — fast & cheap", "gpt-4o-mini"),
        ("GPT-4o      — balanced",     "gpt-4o"),
    ],
    "google": [
        ("Gemini 2.5 Flash — fast & cheap", "gemini-2.5-flash"),
        ("Gemini 2.5 Pro   — most capable", "gemini-2.5-pro"),
    ],
    "ollama": [
        ("llama3.2  — recommended",   "llama3.2"),
        ("llama3.1  — larger",        "llama3.1"),
        ("mistral   — alternative",   "mistral"),
        ("phi3      — fast & small",  "phi3"),
        ("gemma2    — Google",        "gemma2"),
        ("qwen2     — Alibaba",       "qwen2"),
        ("deepseek-r1 — reasoning",   "deepseek-r1"),
    ],
}

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai":    "gpt-4o-mini",
    "google":    "gemini-2.5-flash",
    "ollama":    "llama3.2",
}


def load_saved_keys() -> dict[str, str]:
    """Return raw config dict (slug → key, plus underscore-prefixed metadata)."""
    if not _KEYS_FILE.exists():
        return {}
    try:
        return json.loads(_KEYS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_config(data: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _KEYS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_keys(keys: dict[str, str]) -> None:
    """Persist API keys and inject into current process env vars.
    All underscore-prefixed metadata (selection, model choices) is preserved."""
    saved = load_saved_keys()
    metadata = {k: v for k, v in saved.items() if k.startswith("_")}
    cleaned = {k: v.strip() for k, v in keys.items() if v.strip()}
    cleaned.update(metadata)
    _write_config(cleaned)
    for slug, _, env_var in PROVIDERS:
        val = cleaned.get(slug, "")
        if val:
            os.environ[env_var] = val


def get_model(slug: str) -> str:
    """Return the selected model ID for this provider, or the default."""
    return load_saved_keys().get(f"_model_{slug}") or DEFAULT_MODELS.get(slug, "")


def save_model(slug: str, model_id: str) -> None:
    """Persist the model choice for a provider."""
    saved = load_saved_keys()
    saved[f"_model_{slug}"] = model_id
    _write_config(saved)


def get_selected_provider() -> str | None:
    """Return the slug the user explicitly chose, or None."""
    return load_saved_keys().get("_selected") or None


def set_selected_provider(slug: str | None) -> None:
    """Save (or clear) the user's explicit provider choice."""
    saved = load_saved_keys()
    if slug:
        saved["_selected"] = slug
    else:
        saved.pop("_selected", None)
    _write_config(saved)


def inject_saved_keys() -> None:
    """Load saved keys into env vars. Call once at startup."""
    saved = load_saved_keys()
    for slug, _, env_var in PROVIDERS:
        if not os.environ.get(env_var) and saved.get(slug):
            os.environ[env_var] = saved[slug]


def get_active_provider_name() -> str | None:
    """Return the display name of the provider that will be used.
    Respects the user's explicit selection; falls back to priority order."""
    selected = get_selected_provider()
    if selected:
        for slug, display_name, env_var in PROVIDERS:
            if slug == selected and os.environ.get(env_var, "").strip():
                return display_name
    for _, display_name, env_var in PROVIDERS:
        if os.environ.get(env_var, "").strip():
            return display_name
    return None
