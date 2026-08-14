"""Structured failure classification and rendering contracts."""

from __future__ import annotations

import pytest

from sync_kit.errors import ConfigError, MarkerError, SyncKitError
from sync_kit.reporting import assess_error


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
    assert finding.remediation
    assert finding.source == "Blackout Secure deterministic rules"
