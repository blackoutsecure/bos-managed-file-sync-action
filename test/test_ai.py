from __future__ import annotations

import pytest

from sync_kit.ai import detect_provider, settings_from_section, summarize
from sync_kit.errors import ConfigError


def test_auto_detects_github_models_token():
    provider = detect_provider(environ={"GITHUB_MODELS_TOKEN": "token"})
    assert provider is not None
    assert provider.name == "github-models"
    assert provider.endpoint.startswith("https://")


def test_auto_uses_workflow_token_as_fallback():
    provider = detect_provider(environ={"GITHUB_TOKEN": "token"})
    assert provider is not None
    assert provider.name == "github-models"


def test_no_token_means_no_provider():
    assert detect_provider(environ={}) is None


def test_explicit_disable_skips_detection():
    assert detect_provider("none", environ={"GITHUB_TOKEN": "token"}) is None


def test_external_provider_requires_explicit_endpoint_and_key():
    assert detect_provider("openai", environ={"OPENAI_API_KEY": "key"}) is None
    provider = detect_provider(
        "openai",
        environ={"OPENAI_API_KEY": "key", "OPENAI_API_ENDPOINT": "https://example.test"},
    )
    assert provider is not None
    assert provider.name == "openai"


def test_non_https_endpoint_is_rejected():
    assert (
        detect_provider(
            "openai",
            environ={"OPENAI_API_KEY": "key", "OPENAI_API_ENDPOINT": "file:///etc/passwd"},
        )
        is None
    )
    assert detect_provider(environ={"GITHUB_TOKEN": "t", "GITHUB_MODELS_ENDPOINT": "http://x"}) is None


def test_settings_default_to_opportunistic_ai():
    settings = settings_from_section({})
    assert settings.enable_ai_drift_summary is True
    assert settings.ai_drift_summary_provider == "auto"
    assert settings.local_heuristic_fallback is True


def test_settings_read_the_ai_section():
    settings = settings_from_section(
        {"ai": {"enable_ai_drift_summary": False, "ai_drift_summary_provider": "openai"}}
    )
    assert settings.enable_ai_drift_summary is False
    assert settings.ai_drift_summary_provider == "openai"


def test_settings_reject_non_boolean_flags():
    with pytest.raises(ConfigError):
        settings_from_section({"ai": {"enable_ai_drift_summary": "yes"}})
    with pytest.raises(ConfigError):
        settings_from_section({"ai": "on"})


def test_summarize_returns_none_when_provider_unreachable():
    provider = detect_provider(
        "openai",
        environ={"OPENAI_API_KEY": "key", "OPENAI_API_ENDPOINT": "https://127.0.0.1:1"},
    )
    assert provider is not None
    assert summarize([{"path": "a", "service": "b", "action": "update"}], provider, timeout=1) is None
