from __future__ import annotations

from poker44.miner.config import MinerModelConfig
from poker44.miner.model import ReferenceSessionModel
from poker44.miner.test_models import QualityRiskModel


def config() -> MinerModelConfig:
    return MinerModelConfig(
        factory="poker44.miner.test_models:create_quality_model",
        model_path=None,
        device="cpu",
        version="quality-test-v1",
        max_sessions_per_request=8,
    )


def session(session_id: str) -> dict:
    return {
        "schema_version": "2",
        "session_id": session_id,
        "window_id": "window-1",
        "hands": [{"actions": [{"action_type": "raise"}]}],
        "telemetry": {
            "events": [],
            "summary": {"decision_mean_ms": 400, "decision_std_ms": 30},
        },
    }


def test_full_quality_matches_reference(monkeypatch):
    monkeypatch.setenv("POKER44_TEST_MODEL_QUALITY", "1")
    model = QualityRiskModel(config())
    payload = session("subject-a")

    assert model.predict([payload]) == [ReferenceSessionModel._session_score(payload)]


def test_zero_quality_inverts_reference(monkeypatch):
    monkeypatch.setenv("POKER44_TEST_MODEL_QUALITY", "0")
    model = QualityRiskModel(config())
    payload = session("subject-b")
    reference = ReferenceSessionModel._session_score(payload)

    assert model.predict([payload]) == [round(1.0 - reference, 6)]


def test_quality_must_be_bounded(monkeypatch):
    monkeypatch.setenv("POKER44_TEST_MODEL_QUALITY", "1.1")

    try:
        QualityRiskModel(config())
    except ValueError as error:
        assert "within [0, 1]" in str(error)
    else:
        raise AssertionError("invalid model quality was accepted")
