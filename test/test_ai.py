from __future__ import annotations

import json

import pytest

from sync_kit.ai import detect_provider, recommend_error, settings_from_section, summarize
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
    assert settings.enable_ai_error_remediation is True
    assert settings.ai_error_remediation_provider == "auto"
    assert settings.local_heuristic_fallback is True


def test_settings_read_the_ai_section():
    settings = settings_from_section(
        {
            "ai": {
                "enable_ai_drift_summary": True,
                "ai_drift_summary_provider": "openai",
                "enable_ai_error_remediation": False,
                "ai_error_remediation_provider": "github-models",
            }
        }
    )
    assert settings.enable_ai_drift_summary is True
    assert settings.ai_drift_summary_provider == "openai"
    assert settings.enable_ai_error_remediation is False
    assert settings.ai_error_remediation_provider == "github-models"


def test_disabling_legacy_ai_switch_prohibits_error_model_calls():
    settings = settings_from_section(
        {
            "ai": {
                "enable_ai_drift_summary": False,
                "enable_ai_error_remediation": True,
            }
        }
    )
    assert settings.enable_ai_drift_summary is False
    assert settings.enable_ai_error_remediation is False


def test_settings_reject_non_boolean_flags():
    with pytest.raises(ConfigError):
        settings_from_section({"ai": {"enable_ai_drift_summary": "yes"}})
    with pytest.raises(ConfigError):
        settings_from_section({"ai": "on"})
    with pytest.raises(ConfigError):
        settings_from_section({"ai": {"enable_ai_error_remediation": "yes"}})


def test_summarize_returns_none_when_provider_unreachable():
    provider = detect_provider(
        "openai",
        environ={"OPENAI_API_KEY": "key", "OPENAI_API_ENDPOINT": "https://127.0.0.1:1"},
    )
    assert provider is not None
    assert summarize([{"path": "a", "service": "b", "action": "update"}], provider, timeout=1) is None


def test_error_recommendation_sends_only_allowlisted_metadata(monkeypatch):
    provider = detect_provider(
        "openai",
        environ={"OPENAI_API_KEY": "key", "OPENAI_API_ENDPOINT": "https://example.test"},
    )
    assert provider is not None
    captured: dict = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "recommendation": "Add the missing definition.",
                                        "rationale": "The selected service has no schema object.",
                                        "confidence": "high",
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("sync_kit.ai.urllib.request.urlopen", fake_urlopen)
    recommendation = recommend_error(
        {
            "category": "Missing service definition schema",
            "error_text": "missing schema",
            "location": "managed_file_sync.service_definitions.nope",
            "deterministic_remediation": "Add it.",
            "config_contents": "must not leave the process",
        },
        provider,
        timeout=7,
    )

    assert recommendation is not None
    assert recommendation.recommendation == "Add the missing definition."
    assert recommendation.confidence == "High"
    assert captured["timeout"] == 7
    sent = json.loads(captured["payload"]["messages"][1]["content"])
    assert set(sent) == {
        "category",
        "error_text",
        "location",
        "deterministic_remediation",
    }
    assert "config_contents" not in sent
