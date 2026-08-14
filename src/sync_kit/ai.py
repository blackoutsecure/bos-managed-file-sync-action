"""Opportunistic AI drift summaries with a deterministic local fallback.

AI is never required: when no provider is configured, no credential is present,
or a request fails, callers fall back to the deterministic summary and the run
continues unchanged. Only drift metadata (path, service, action) is ever sent —
never file contents or diffs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ConfigError

GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_GITHUB_MODEL = "openai/gpt-4o-mini"

_GITHUB_PROVIDER_NAMES = {"auto", "github", "github-models", "copilot"}
_DISABLED_PROVIDER_NAMES = {"none", "disabled", "false", "off"}


def _https_endpoint(value: str | None) -> str | None:
    """Accept only HTTPS endpoints so env overrides cannot switch scheme."""
    endpoint = (value or "").strip()
    return endpoint if endpoint.startswith("https://") else None


@dataclass(frozen=True)
class Provider:
    """A resolved, usable AI endpoint."""

    name: str
    endpoint: str
    model: str
    token: str


@dataclass(frozen=True)
class AISettings:
    """Repo policy for AI-assisted output."""

    enable_ai_drift_summary: bool = True
    ai_drift_summary_provider: str = "auto"
    local_heuristic_fallback: bool = True


def settings_from_section(section: dict[str, Any]) -> AISettings:
    """Read the optional ``ai`` block from a merged config section."""
    raw = section.get("ai")
    if raw is None:
        return AISettings()
    if not isinstance(raw, dict):
        raise ConfigError("'ai' must be a JSON object")

    def flag(key: str, default: bool) -> bool:
        value = raw.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise ConfigError(f"'ai.{key}' must be true or false")
        return value

    provider = raw.get("ai_drift_summary_provider", "auto")
    if not isinstance(provider, str):
        raise ConfigError("'ai.ai_drift_summary_provider' must be a string")

    return AISettings(
        enable_ai_drift_summary=flag("enable_ai_drift_summary", True),
        ai_drift_summary_provider=provider,
        local_heuristic_fallback=flag("local_heuristic_fallback", True),
    )


def detect_provider(
    configured: str = "",
    *,
    environ: Mapping[str, str] | None = None,
) -> Provider | None:
    """Select an explicitly configured provider, or GitHub Models when available.

    A token that turns out to lack model access is treated as normal
    unavailability by :func:`summarize`; it never fails the run. External
    providers require both an explicit provider name and an endpoint.
    """
    env = os.environ if environ is None else environ
    name = (configured or "auto").strip().lower()
    if name in _DISABLED_PROVIDER_NAMES:
        return None

    if name in _GITHUB_PROVIDER_NAMES:
        token = env.get("GITHUB_MODELS_TOKEN") or env.get("GITHUB_TOKEN")
        endpoint = _https_endpoint(env.get("GITHUB_MODELS_ENDPOINT", GITHUB_MODELS_ENDPOINT))
        if token and endpoint:
            return Provider(
                name="github-models",
                endpoint=endpoint,
                model=env.get("GITHUB_MODELS_MODEL", DEFAULT_GITHUB_MODEL),
                token=token,
            )
        return None

    prefix = name.upper().replace("-", "_")
    token = env.get(f"{prefix}_API_KEY") or env.get("AI_API_KEY")
    endpoint = _https_endpoint(env.get(f"{prefix}_API_ENDPOINT") or env.get("AI_API_ENDPOINT"))
    if token and endpoint:
        return Provider(
            name=name,
            endpoint=endpoint,
            model=env.get(f"{prefix}_MODEL", ""),
            token=token,
        )
    return None


def summarize(
    changes: list[dict[str, str]],
    provider: Provider,
    *,
    timeout: int = 20,
) -> str | None:
    """Request a short drift summary; return ``None`` for any error."""
    payload = {
        "model": provider.model,
        "messages": [
            {
                "role": "system",
                "content": "You summarize repository managed-file drift for a CI job summary.",
            },
            {
                "role": "user",
                "content": (
                    "Summarize this managed-file drift in at most three concise bullets. "
                    "Group by service, state what will change, and do not invent facts.\n\n"
                    + json.dumps(changes, ensure_ascii=True)
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 300,
    }
    request = urllib.request.Request(  # noqa: S310 - scheme restricted to https by detect_provider
        provider.endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {provider.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
    except (OSError, ValueError, KeyError, IndexError, urllib.error.URLError):
        return None
    if not isinstance(content, str):
        return None
    return content.strip() or None
