import pytest

from poker44.platform.models import (
    SessionLease,
    ValidationRound,
    canonical_dataset_hash,
)


def lease_payload():
    payload = {
        "lease_id": "lease-1",
        "window_id": "window-1",
        "dataset_hash": "",
        "expires_at": "2026-07-15T12:00:00Z",
        "sessions": [
            {
                "is_bot": False,
                "payload": {
                    "schema_version": "1",
                    "session_id": "human-1",
                    "window_id": "window-1",
                    "hands": [{}],
                    "telemetry": {"events": [], "summary": {}},
                },
            },
            {
                "is_bot": True,
                "payload": {
                    "schema_version": "1",
                    "session_id": "bot-1",
                    "window_id": "window-1",
                    "hands": [{}],
                    "telemetry": {"events": [], "summary": {}},
                },
            },
        ],
    }
    payload["dataset_hash"] = canonical_dataset_hash(
        [item["payload"] for item in payload["sessions"]]
    )
    return payload


def test_cycle_keeps_labels_outside_miner_payload():
    validation_round = ValidationRound(SessionLease.from_payload(lease_payload()))

    assert validation_round.round_id == "window-1"
    assert validation_round.labels == [0, 1]
    assert all("is_bot" not in session for session in validation_round.miner_sessions)


def test_lease_rejects_label_leak_inside_payload():
    payload = lease_payload()
    payload["sessions"][0]["payload"]["label"] = "human"
    with pytest.raises(ValueError, match="leaks labels"):
        SessionLease.from_payload(payload)


def test_lease_preserves_completion_state_for_idempotent_restarts():
    payload = lease_payload()
    payload["completed_at"] = "2026-07-15T12:01:00Z"

    lease = SessionLease.from_payload(payload)

    assert lease.completed_at == "2026-07-15T12:01:00Z"


def test_lease_rejects_payloads_that_do_not_match_the_common_dataset_hash():
    payload = lease_payload()
    payload["sessions"][0]["payload"]["session_id"] = "tampered"

    with pytest.raises(ValueError, match="dataset_hash"):
        SessionLease.from_payload(payload)
