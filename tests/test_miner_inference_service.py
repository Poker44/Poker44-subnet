from __future__ import annotations

import pytest

from poker44.miner.config import MinerModelConfig
from poker44.miner.model import ReferenceSessionModel
from poker44.miner.service import MinerInferenceService


def make_session(**overrides):
    session = {
        "schema_version": "2",
        "session_id": "session-1",
        "window_id": "window-1",
        "hands": [{"actions": [{"action_type": "check"}]}],
        "telemetry": {
            "events": [
                {
                    "sequence": 0,
                    "offset_ms": 10,
                    "event_type": "click",
                    "target_category": "poker_action",
                    "value": {"button": 0},
                }
            ],
            "summary": {"decision_mean_ms": 1200, "decision_std_ms": 100},
        },
    }
    session.update(overrides)
    return session


def make_service(max_sessions=8):
    config = MinerModelConfig(
        factory="poker44.miner.model:create_reference_model",
        model_path=None,
        device="cpu",
        version="test-v1",
        max_sessions_per_request=max_sessions,
    )
    model = ReferenceSessionModel(config)
    model.load()
    return MinerInferenceService(model, config)


@pytest.mark.asyncio
async def test_model_returns_one_bounded_score_per_session():
    scores = await make_service().predict(
        [make_session(), make_session(session_id="session-2")]
    )

    assert len(scores) == 2
    assert all(0.0 <= score <= 1.0 for score in scores)


@pytest.mark.asyncio
async def test_model_accepts_legacy_session_protocol_v1_during_migration():
    scores = await make_service().predict([make_session(schema_version="1")])

    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0


@pytest.mark.asyncio
async def test_future_session_protocol_is_rejected():
    with pytest.raises(ValueError, match="unsupported schema_version"):
        await make_service().predict([make_session(schema_version="3")])


@pytest.mark.asyncio
async def test_ground_truth_is_rejected_at_miner_boundary():
    with pytest.raises(ValueError, match="ground-truth"):
        await make_service().predict([make_session(is_bot=True)])


@pytest.mark.asyncio
async def test_nested_ground_truth_is_rejected_at_miner_boundary():
    session = make_session()
    session["telemetry"]["summary"]["bot_family"] = "leaked-family"
    with pytest.raises(ValueError, match="ground-truth"):
        await make_service().predict([session])


@pytest.mark.asyncio
async def test_non_finite_model_output_is_rejected():
    service = make_service()
    service.model.predict = lambda _sessions: [float("nan")]
    with pytest.raises(ValueError, match="finite"):
        await service.predict([make_session()])


@pytest.mark.asyncio
async def test_request_limit_is_enforced():
    with pytest.raises(ValueError, match="maximum"):
        await make_service(max_sessions=1).predict(
            [make_session(), make_session(session_id="session-2")]
        )


@pytest.mark.asyncio
async def test_request_byte_limit_is_enforced():
    service = make_service()
    object.__setattr__(service.config, "max_request_bytes", 10)
    with pytest.raises(ValueError, match="bytes"):
        await service.predict([make_session()])
