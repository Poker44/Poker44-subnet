from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from neurons.validator import Validator
from poker44.platform.models import LeasedSession, SessionLease, ValidationRound
from poker44.protocol import MicroSessionDetectionSynapse
from poker44.validator.evaluation.mixin import ValidatorEvaluationMixin
from poker44.validator.evaluation.models import MinerEvaluation


@pytest.mark.asyncio
async def test_round_flows_from_platform_lease_through_rewards_and_weights():
    lease = SessionLease(
        lease_id="lease-1",
        window_id="round-1",
        dataset_hash="sha256:dataset",
        expires_at="2099-01-01T00:00:00Z",
        sessions=[
            LeasedSession(
                payload={
                    "item_id": "item-1",
                    "schema_version": "4.1",
                    "window_id": "round-1",
                },
                is_bot=True,
            )
        ],
    )
    validation_round = ValidationRound(lease=lease)
    evaluation = MinerEvaluation(
        uid=4,
        hotkey="miner-hotkey",
        quality_score=0.9,
        metrics={"accuracy": 1.0},
        response_seconds=0.1,
        model_version="model-v1",
    )
    calls: list[str] = []

    validator = SimpleNamespace(
        poll_interval=0,
        subnet_data=SimpleNamespace(
            complete_lease=Mock(side_effect=lambda *_: calls.append("complete_lease"))
        ),
        round_manager=SimpleNamespace(
            complete=Mock(side_effect=lambda *_: calls.append("complete_round")),
            fail=Mock(),
        ),
        _reconcile_pending_weight_reveals=AsyncMock(),
        _attempt_pending_weight_settlement=AsyncMock(),
        _report_event=AsyncMock(),
    )
    validator._start_validation_round = AsyncMock(
        side_effect=lambda *_: (
            calls.append("load_platform_sessions"),
            validation_round,
        )[1]
    )
    validator._run_evaluation_phase = AsyncMock(
        side_effect=lambda _: (
            calls.append("query_miners_and_compute_rewards"),
            [evaluation],
        )[1]
    )
    validator._run_settlement_phase = AsyncMock(
        side_effect=lambda *_: (
            calls.append("compute_and_set_weights"),
            {"weights": [{"uid": 4, "weight": 1.0}], "submitted": True},
        )[1]
    )

    with patch("neurons.validator.asyncio.sleep", new=AsyncMock()):
        await Validator.forward(validator)

    assert calls == [
        "load_platform_sessions",
        "query_miners_and_compute_rewards",
        "compute_and_set_weights",
        "complete_lease",
        "complete_round",
    ]
    validator.subnet_data.complete_lease.assert_called_once_with("lease-1", "round-1")
    validator.round_manager.complete.assert_called_once_with("round-1")
    validator.round_manager.fail.assert_not_called()


@pytest.mark.asyncio
async def test_failed_round_reports_backoff_and_terminal_state():
    validation_round = ValidationRound(
        lease=SessionLease(
            lease_id="lease-1",
            window_id="round-1",
            dataset_hash="hash",
            expires_at="2099-01-01T00:00:00Z",
            sessions=[
                LeasedSession(
                    payload={"item_id": "i1", "schema_version": "4.1"}, is_bot=True
                )
            ],
        )
    )
    validator = SimpleNamespace(
        poll_interval=0,
        round_manager=SimpleNamespace(fail=Mock(return_value=None)),
        _reconcile_pending_weight_reveals=AsyncMock(),
        _attempt_pending_weight_settlement=AsyncMock(),
        _start_validation_round=AsyncMock(return_value=validation_round),
        _run_evaluation_phase=AsyncMock(side_effect=RuntimeError("miner failure")),
        _report_event=AsyncMock(),
    )

    with (
        patch("neurons.validator.asyncio.sleep", new=AsyncMock()),
        pytest.raises(RuntimeError, match="miner failure"),
    ):
        await Validator.forward(validator)

    validator.round_manager.fail.assert_called_once_with("round-1")
    validator._report_event.assert_awaited_once_with(
        "validation_round_failed",
        validation_round,
        {
            "error": "miner failure",
            "retry_in_seconds": None,
            "terminal": True,
        },
    )


@pytest.mark.asyncio
async def test_transient_missing_miner_response_is_retried():
    valid = SimpleNamespace(risk_scores=[0.2])
    missing = SimpleNamespace(risk_scores=None)
    recovered = SimpleNamespace(risk_scores=[0.8])
    validator = SimpleNamespace(
        dendrite=AsyncMock(return_value=[recovered]),
        config=SimpleNamespace(neuron=SimpleNamespace(timeout=10)),
    )
    synapse = MicroSessionDetectionSynapse(
        window_id="window-1",
        dataset_hash="a" * 64,
        query_id="query",
        items=[{"schema_version": "4.1"}],
    )

    merged = await ValidatorEvaluationMixin._retry_transient_responses(
        validator,
        uids=[2, 3],
        axons=["axon-2", "axon-3"],
        synapse=synapse,
        responses=[valid, missing],
    )

    assert merged == [valid, recovered]
    validator.dendrite.assert_awaited_once_with(
        axons=["axon-3"],
        synapse=synapse,
        deserialize=False,
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_waits_two_minutes_before_logging_and_retrying_missing_miners():
    valid = SimpleNamespace(risk_scores=[0.2])
    missing = SimpleNamespace(risk_scores=None)

    with patch(
        "poker44.validator.evaluation.mixin.asyncio.sleep", new=AsyncMock()
    ) as sleep:
        await ValidatorEvaluationMixin._wait_before_miner_retry(
            uids=[2, 3], responses=[valid, missing]
        )

    sleep.assert_awaited_once_with(120.0)


def test_miner_evaluation_log_shows_summary_and_per_miner_status():
    evaluations = [
        MinerEvaluation(
            uid=2,
            hotkey="successful-miner",
            quality_score=0.75,
            metrics={"accuracy": 1.0},
            response_seconds=0.25,
            model_version="v1",
        ),
        MinerEvaluation(
            uid=3,
            hotkey="failed-miner",
            quality_score=0.0,
            metrics={},
            response_seconds=None,
            model_version=None,
            error="missing risk_scores",
        ),
    ]
    responses = [
        SimpleNamespace(dendrite=SimpleNamespace(status_code=200)),
        SimpleNamespace(dendrite=SimpleNamespace(status_code=408)),
    ]

    with patch("poker44.validator.evaluation.mixin.bt.logging.info") as log:
        ValidatorEvaluationMixin._log_miner_evaluations(
            stage="before_retry",
            evaluations=evaluations,
            responses=responses,
        )

    messages = [call.args[0] for call in log.call_args_list]
    assert "stage=before_retry successful=1/2 failed=1" in messages[0]
    assert "✓ UID 2" in messages[1]
    assert "score=0.750000" in messages[1]
    assert "✗ UID 3" in messages[2]
    assert "error=missing risk_scores" in messages[2]


def test_missing_trailing_miner_response_is_preserved_for_retry():
    response = SimpleNamespace(risk_scores=[0.2])

    aligned = ValidatorEvaluationMixin._align_responses([response], 2)

    assert aligned == [response, None]


def test_scores_file_contains_round_date_top_and_every_component(monkeypatch, tmp_path):
    scores_path = tmp_path / "scores.txt"
    monkeypatch.setattr(
        "poker44.validator.evaluation.mixin.Path.resolve",
        lambda _path: tmp_path / "poker44/validator/evaluation/mixin.py",
    )
    response = SimpleNamespace(
        dendrite=SimpleNamespace(
            process_time=0.25,
            status_code=200,
            status_message="OK",
        ),
        model_version="model-v1",
    )
    axon = SimpleNamespace(ip="192.0.2.10", port=8091)
    evaluation = MinerEvaluation(
        uid=3,
        hotkey="miner-hotkey",
        quality_score=0.75,
        metrics={
            "reward": 0.75,
            "average_precision": 0.8,
            "average_precision_skill": 0.7,
            "recall_at_fpr_05": 0.6,
            "false_positive_rate": 0.04,
            "brier_skill": 0.5,
            "accuracy": 0.9,
        },
        response_seconds=0.25,
        model_version="model-v1",
    )

    ValidatorEvaluationMixin._write_miner_evaluations(
        round_id="round-123",
        stage="before_retry",
        evaluations=[evaluation],
        responses=[response],
        axons=[axon],
    )

    contents = scores_path.read_text()
    assert "ROUND: round-123" in contents
    assert "DATE (UTC):" in contents
    assert "SNAPSHOT: BEFORE RETRY" in contents
    assert "TOP MINER" in contents
    assert "UID: 3" in contents
    assert "Total score: 0.750000" in contents
    for component in evaluation.metrics:
        assert contents.count(f'"{component}"') == 2
    assert "Status: 200 (OK)" in contents
    assert contents.count("miner-hotkey") == 2
    assert contents.count("192.0.2.10:8091") == 2
    assert contents.count("0.25s") == 2
    assert scores_path.stat().st_mode & 0o777 == 0o600


def test_scores_file_appends_after_retry_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "poker44.validator.evaluation.mixin.Path.resolve",
        lambda _path: tmp_path / "poker44/validator/evaluation/mixin.py",
    )
    response = SimpleNamespace(
        dendrite=SimpleNamespace(status_code=408, status_message="Timeout"),
    )
    axon = SimpleNamespace(ip="192.0.2.20", port=8092)
    evaluation = MinerEvaluation(
        uid=4,
        hotkey="failed-miner",
        quality_score=0.0,
        metrics={},
        response_seconds=None,
        model_version=None,
        error="missing risk_scores",
    )

    ValidatorEvaluationMixin._write_miner_evaluations(
        round_id="round-failed",
        stage="before_retry",
        evaluations=[evaluation],
        responses=[response],
        axons=[axon],
    )
    ValidatorEvaluationMixin._write_miner_evaluations(
        round_id="round-failed",
        stage="after_retry",
        evaluations=[evaluation],
        responses=[response],
        axons=[axon],
    )

    contents = (tmp_path / "scores.txt").read_text()
    assert contents.count("ROUND: round-failed") == 2
    assert contents.count("DATE (UTC):") == 2
    assert contents.count("SNAPSHOT: BEFORE RETRY") == 1
    assert contents.count("SNAPSHOT: AFTER RETRY") == 1
    assert contents.count("Total score: 0.000000") == 4
    assert contents.count("Error: missing risk_scores") == 2
    assert contents.count("192.0.2.20:8092") == 4


@pytest.mark.asyncio
async def test_evaluated_round_resumes_without_querying_miners():
    validation_round = ValidationRound(
        lease=SessionLease(
            lease_id="lease-resume",
            window_id="window-resume",
            dataset_hash="hash",
            expires_at="2099-01-01T00:00:00Z",
            sessions=[
                LeasedSession(
                    payload={"item_id": "i1", "schema_version": "4.1"}, is_bot=True
                )
            ],
        ),
        resume_state="EVALUATED",
        resume_evidence={
            "evaluations": [
                {
                    "uid": 4,
                    "hotkey": "miner",
                    "quality_score": 0.75,
                    "metrics": {"accuracy": 1.0},
                    "response_seconds": 0.1,
                    "model_version": "v4",
                    "error": None,
                }
            ]
        },
    )
    validator = SimpleNamespace(dendrite=AsyncMock())

    restored = await ValidatorEvaluationMixin._run_evaluation_phase(
        validator, validation_round
    )

    assert restored[0].uid == 4
    validator.dendrite.assert_not_awaited()
