from poker44.protocol import SessionDetectionSynapse


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
