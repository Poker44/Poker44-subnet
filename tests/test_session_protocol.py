import pytest

from poker44.protocol import SessionDetectionSynapse, validate_session_request


def test_session_synapse_has_no_ground_truth_field():
    synapse = SessionDetectionSynapse(
        window_id="window-1",
        dataset_hash="a" * 64,
        sessions=[
            {
                "schema_version": "2",
                "session_id": "session-1",
                "window_id": "window-1",
                "hands": [{"actions": []}],
                "telemetry": {"events": [], "summary": {}},
            }
        ],
    )

    assert synapse.window_id == "window-1"
    assert synapse.dataset_hash == "a" * 64
    assert len(synapse.sessions) == 1
    assert "labels" not in type(synapse).model_fields
    assert "ground_truth" not in type(synapse).model_fields


def test_protocol_v2_request_requires_dataset_hash():
    synapse = SessionDetectionSynapse(
        protocol_version="2",
        window_id="window-1",
        dataset_hash="a" * 64,
        sessions=[],
    )

    validate_session_request(synapse)

    synapse.dataset_hash = ""
    with pytest.raises(ValueError, match="dataset_hash"):
        validate_session_request(synapse)


def test_legacy_protocol_v1_request_remains_supported():
    validate_session_request(
        SessionDetectionSynapse(
            protocol_version="1",
            window_id="window-legacy",
            sessions=[],
        )
    )


def test_unknown_protocol_version_is_rejected():
    with pytest.raises(ValueError, match="Unsupported Poker44 protocol version"):
        validate_session_request(
            SessionDetectionSynapse(
                protocol_version="3",
                window_id="window-1",
                dataset_hash="a" * 64,
                sessions=[],
            )
        )
