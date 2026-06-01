from __future__ import annotations

from copy import deepcopy

from app.services.report_sanitizer import sanitize_record, sanitize_report_metadata
from app.utils.masking import MASK


def test_observability_sanitizer_masks_nested_secret_fields_without_mutation() -> None:
    payload = {
        "device_id": "device-1",
        "hostname": "edge-1",
        "nested": {
            "password": "SHOULD_NOT_LEAK",
            "api_token": "SHOULD_NOT_LEAK",
            "safe_count": 2,
            "items": [{"raw_config": "username admin secret SHOULD_NOT_LEAK"}, "password simple SHOULD_NOT_LEAK"],
        },
    }
    original = deepcopy(payload)

    sanitized = sanitize_report_metadata(payload)

    assert payload == original
    assert sanitized["device_id"] == "device-1"
    assert sanitized["hostname"] == "edge-1"
    assert sanitized["nested"]["password"] == MASK
    assert sanitized["nested"]["api_token"] == MASK
    assert sanitized["nested"]["items"][0]["raw_config"] == MASK
    assert "SHOULD_NOT_LEAK" not in str(sanitized)


def test_observability_sanitizer_is_deterministic_and_keeps_safe_metadata() -> None:
    payload = {"z": "safe", "a": {"status": "ready", "risk_level": "low"}, "secret": "SHOULD_NOT_LEAK"}

    first = sanitize_record(payload)
    second = sanitize_record(payload)

    assert first == second
    assert list(first) == ["a", "secret", "z"]
    assert first["a"]["status"] == "ready"
    assert first["secret"] == MASK


def test_observability_sanitizer_preserves_safe_workflow_count_keys() -> None:
    payload = {
        "workflow_summary": {"by_type": {"password_rollout": 2, "vlan_workflow": 1}},
        "workflow_counts_by_type": {"password_rollout": 2, "vlan_workflow": 1},
        "credential_summary": {"valid_credentials": 3, "invalid_credentials": 1},
        "new_password": "SHOULD_NOT_LEAK",
        "password_rollout_secret": "SHOULD_NOT_LEAK",
        "apiToken": "SHOULD_NOT_LEAK",
        "privateKey": "SHOULD_NOT_LEAK",
        "rawConfig": "SHOULD_NOT_LEAK",
    }

    sanitized = sanitize_record(payload)

    assert sanitized["workflow_summary"]["by_type"]["password_rollout"] == 2
    assert sanitized["workflow_counts_by_type"]["password_rollout"] == 2
    assert sanitized["credential_summary"]["valid_credentials"] == 3
    assert sanitized["new_password"] == MASK
    assert sanitized["password_rollout_secret"] == MASK
    assert sanitized["apiToken"] == MASK
    assert sanitized["privateKey"] == MASK
    assert sanitized["rawConfig"] == MASK
    assert "SHOULD_NOT_LEAK" not in str(sanitized)
