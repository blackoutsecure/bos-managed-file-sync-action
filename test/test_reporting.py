"""Structured failure classification and rendering contracts."""

from __future__ import annotations

import pytest

from sync_kit.errors import ConfigError, MarkerError, SyncKitError
from sync_kit.reporting import ReportingSettings, assess_error, reporting_settings


def test_reporting_settings_match_automation_hub_defaults():
    assert reporting_settings({}) == ReportingSettings()


def test_reporting_settings_normalize_organization_overrides():
    settings = reporting_settings(
        {
            "organization": {
                "reporting": {
                    "enable_job_summary": False,
                    "enable_annotations": False,
                    "enable_html": False,
                    "enable_pdf": True,
                    "html_path": "reports/sync.html",
                    "pdf_path": "reports/sync.pdf",
                    "artifact_name": "managed-file-report",
                    "title_prefix": "Example Org",
                    "fail_on": "never",
                }
            }
        }
    )

    assert settings == ReportingSettings(
        enable_job_summary=False,
        enable_annotations=False,
        enable_html=False,
        enable_pdf=True,
        html_path="reports/sync.html",
        pdf_path="reports/sync.pdf",
        artifact_name="managed-file-report",
        title_prefix="Example Org",
        fail_on="never",
    )


@pytest.mark.parametrize(
    ("reporting", "message"),
    [
        ({"enable_job_summary": "false"}, "enable_job_summary"),
        ({"fail_on": "sometimes"}, "fail_on"),
        ({"html_path": "../report.html"}, "html_path"),
        ({"artifact_name": "reports/sync"}, "artifact_name"),
    ],
)
def test_reporting_settings_reject_invalid_policy(reporting, message):
    with pytest.raises(ConfigError, match=message):
        reporting_settings({"organization": {"reporting": reporting}})


@pytest.mark.parametrize("organization", [False, [], "invalid"])
def test_reporting_settings_reject_invalid_organization_container(organization):
    with pytest.raises(ConfigError, match="'organization' must be a JSON object"):
        reporting_settings({"organization": organization})


@pytest.mark.parametrize("reporting", [False, [], "invalid"])
def test_reporting_settings_reject_invalid_reporting_container(reporting):
    with pytest.raises(
        ConfigError,
        match="'organization.reporting' must be a JSON object",
    ):
        reporting_settings({"organization": {"reporting": reporting}})


@pytest.mark.parametrize(
    ("error", "rule_id", "category"),
    [
        (
            ConfigError("content_file not found: templates/common.txt"),
            "MFS-CFG-005",
            "Managed content template not found",
        ),
        (
            MarkerError("managed block for service 'common' must contain exactly one start marker"),
            "MFS-MARKER-001",
            "Managed block ownership or marker error",
        ),
        (
            ConfigError("managed path must not be a symbolic link: .github/file.yml"),
            "MFS-SAFE-001",
            "Unsafe managed path",
        ),
        (
            ConfigError("managed path changed during sync; retry: .github/file.yml"),
            "MFS-FS-002",
            "Concurrent filesystem change",
        ),
        (
            ConfigError("managed content must be valid UTF-8: .github/file.yml"),
            "MFS-FS-001",
            "Managed file I/O error",
        ),
        (
            ConfigError("services 'a' (file) and 'b' (file) both claim path 'x'"),
            "MFS-CFG-006",
            "Conflicting managed path ownership",
        ),
        (
            ConfigError("'services' must be a list or an object of name -> bool"),
            "MFS-CFG-003",
            "Invalid managed-file-sync schema",
        ),
        (
            SyncKitError("unexpected runtime condition"),
            "MFS-RUN-000",
            "Managed-file-sync runtime error",
        ),
    ],
)
def test_error_classifier_assigns_specific_stable_rules(error, rule_id, category):
    finding = assess_error(error)

    assert finding.rule_id == rule_id
    assert finding.category == category
    assert finding.severity == "fail"
    assert finding.remediation
    assert finding.source == "Blackout Secure deterministic rules"
