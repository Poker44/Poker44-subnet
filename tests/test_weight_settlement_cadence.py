from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from poker44.validator.settlement.mixin import ValidatorSettlementMixin


def _harness(
    tmp_path, *, current_block: int, last_update: int = 0, rate_limit: int = 100
):
    subtensor = SimpleNamespace(
        get_subnet_hyperparameters=Mock(
            return_value=SimpleNamespace(weights_rate_limit=rate_limit)
        ),
        get_current_block=Mock(return_value=current_block),
        commit_reveal_enabled=Mock(return_value=False),
    )
    harness = SimpleNamespace(
        config=SimpleNamespace(
            netuid=44,
            neuron=SimpleNamespace(
                full_path=str(tmp_path),
                wait_for_finalization=False,
            ),
        ),
        uid=0,
        metagraph=SimpleNamespace(last_update=[last_update], hotkeys=["validator", "one", "winner"]),
        subtensor=subtensor,
        subnet_data=SimpleNamespace(advance_evaluation_run=Mock(return_value=True)),
        set_weights=Mock(return_value=True),
        _report_event=AsyncMock(),
        _pending_weight_commits=AsyncMock(return_value=[]),
        _prepared_weights_from_rows=ValidatorSettlementMixin._prepared_weights_from_rows,
    )
    harness._weight_settlement_state_path = lambda: tmp_path / "weight_settlement.json"
    harness._load_weight_settlement = MethodType(
        ValidatorSettlementMixin._load_weight_settlement, harness
    )
    harness._save_weight_settlement = MethodType(
        ValidatorSettlementMixin._save_weight_settlement, harness
    )
    harness._weight_submission_is_due = MethodType(
        ValidatorSettlementMixin._weight_submission_is_due, harness
    )
    harness._ensure_settlement_target_is_launched = MethodType(
        ValidatorSettlementMixin._ensure_settlement_target_is_launched, harness
    )
    harness._append_settlement_history = MethodType(
        ValidatorSettlementMixin._append_settlement_history, harness
    )
    harness._settlement_history_path = lambda: tmp_path / "settlement_history.jsonl"
    return harness


@pytest.mark.asyncio
async def test_pending_commits_reads_every_finalized_storage_bucket(monkeypatch):
    first = ("other-validator", 100, "cipher-one", 1_000)
    second = ("validator", 101, "cipher-two", 1_001)
    result = SimpleNamespace(records=[("bucket-one", [first]), ("bucket-two", [second])])
    substrate = SimpleNamespace(
        get_chain_finalised_head=Mock(return_value="0xfinalized"),
        query_map=Mock(return_value=result),
    )
    harness = SimpleNamespace(
        config=SimpleNamespace(netuid=44),
        subtensor=SimpleNamespace(substrate=substrate),
        wallet=SimpleNamespace(hotkey=SimpleNamespace(ss58_address="validator")),
    )
    harness._all_timelocked_weight_commits = MethodType(
        ValidatorSettlementMixin._all_timelocked_weight_commits, harness
    )
    monkeypatch.setattr(
        "poker44.validator.settlement.mixin.WeightCommitInfo.from_vec_u8_v2",
        lambda commit: commit,
    )

    commits = await ValidatorSettlementMixin._pending_weight_commits(harness)

    assert commits == [
        {"hotkey": "validator", "commit_block": 101, "reveal_round": 1_001}
    ]
    substrate.query_map.assert_called_once_with(
        module="SubtensorModule",
        storage_function="TimelockedWeightCommits",
        params=[44],
        block_hash="0xfinalized",
        page_size=100,
        max_results=1_000,
    )


def test_new_round_replaces_target_and_keeps_unsettled_run_evidence(tmp_path):
    harness = _harness(tmp_path, current_block=10)
    harness._record_weight_settlement = MethodType(
        ValidatorSettlementMixin._record_weight_settlement, harness
    )
    first = SimpleNamespace(
        round_id="round-one",
        lease=SimpleNamespace(
            window_id="window-one",
            launch_status="LAUNCHED",
        ),
    )
    second = SimpleNamespace(
        round_id="round-two",
        lease=SimpleNamespace(
            window_id="window-two",
            launch_status="LAUNCHED",
        ),
    )

    harness._record_weight_settlement(first, [{"uid": 1, "hotkey": "one", "weight": 1.0}])
    harness._record_weight_settlement(
        second,
        [{"uid": 2, "hotkey": "winner", "weight": 1.0}],
    )

    state = harness._load_weight_settlement()
    assert state["version"] == 4
    assert state["weights"] == [{"uid": 2, "hotkey": "winner", "weight": 1.0}]
    assert state["evaluation_runs"] == [
        {
            "round_id": "round-one",
            "window_id": "window-one",
        },
        {
            "round_id": "round-two",
            "window_id": "window-two",
        },
    ]


def test_new_round_discards_automatic_recovery_evidence(tmp_path):
    harness = _harness(tmp_path, current_block=10)
    harness._record_weight_settlement = MethodType(
        ValidatorSettlementMixin._record_weight_settlement, harness
    )
    harness._save_weight_settlement(
        {
            "version": 3,
            "dirty": True,
            "round_id": "recovery:old-round",
            "window_id": "old-window",
            "evaluation_runs": [
                {"round_id": "recovery:old-round", "window_id": "old-window"}
            ],
            "weights": [{"uid": 9, "hotkey": "old", "weight": 1.0}],
            "recovery_of": {"window_id": "old-window"},
        }
    )
    current = SimpleNamespace(
        round_id="new-round",
        lease=SimpleNamespace(window_id="new-window", launch_status="LAUNCHED"),
    )

    harness._record_weight_settlement(
        current, [{"uid": 2, "hotkey": "winner", "weight": 1.0}]
    )

    state = harness._load_weight_settlement()
    assert state["round_id"] == "new-round"
    assert state["evaluation_runs"] == [
        {"round_id": "new-round", "window_id": "new-window"}
    ]
    assert "recovery_of" not in state


@pytest.mark.asyncio
async def test_dirty_weights_remain_pending_until_chain_rate_limit_allows(tmp_path):
    harness = _harness(tmp_path, current_block=100, rate_limit=100)
    harness._save_weight_settlement(
        {
            "version": 1,
            "dirty": True,
            "window_id": "window-1",
            "round_id": "round-1",
            "weights": [{"uid": 2, "hotkey": "winner", "weight": 1.0}],
        }
    )

    submitted = await ValidatorSettlementMixin._attempt_pending_weight_settlement(
        harness
    )

    assert submitted is False
    assert harness._load_weight_settlement()["dirty"] is True
    harness.set_weights.assert_not_called()


@pytest.mark.asyncio
async def test_pending_weights_submit_once_allowed_and_refresh_after_720_blocks(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("POKER44_WEIGHT_REFRESH_BLOCKS", "720")
    harness = _harness(tmp_path, current_block=101, rate_limit=100)
    harness._save_weight_settlement(
        {
            "version": 1,
            "dirty": True,
            "window_id": "window-1",
            "round_id": "round-1",
            "weights": [{"uid": 2, "hotkey": "winner", "weight": 1.0}],
        }
    )

    assert (
        await ValidatorSettlementMixin._attempt_pending_weight_settlement(harness)
        is True
    )
    state = harness._load_weight_settlement()
    assert state["dirty"] is False
    assert state["last_submission_block"] == 101
    assert harness.set_weights.call_count == 1

    harness.subtensor.get_current_block.return_value = 820
    assert (
        await ValidatorSettlementMixin._attempt_pending_weight_settlement(harness)
        is False
    )
    assert harness.set_weights.call_count == 1

    harness.subtensor.get_current_block.return_value = 821
    assert (
        await ValidatorSettlementMixin._attempt_pending_weight_settlement(harness)
        is True
    )
    assert harness.set_weights.call_count == 2
    assert harness._report_event.await_args_list[-1].args[0] == "weights_refreshed"


@pytest.mark.asyncio
async def test_automatic_recovery_target_is_never_submitted(tmp_path):
    harness = _harness(tmp_path, current_block=500, rate_limit=100)
    harness.metagraph.hotkeys = ["validator", "prior-winner", "funding", "bad-winner"]
    invalid_rows = [
        {"uid": 0, "hotkey": "validator", "weight": 0.30},
        {"uid": 2, "hotkey": "funding", "weight": 0.05},
        {"uid": 3, "hotkey": "bad-winner", "weight": 0.65},
    ]
    harness._save_weight_settlement(
        {
            "version": 3,
            "dirty": False,
            "window_id": "observation-window",
            "round_id": "observation-window",
            "weights": invalid_rows,
            "last_submission_block": 400,
            "recovery_of": {"window_id": "observation-window"},
        }
    )

    launched = await harness._ensure_settlement_target_is_launched(
        harness._load_weight_settlement()
    )

    assert launched is False
    state = harness._load_weight_settlement()
    assert state["weights"] == invalid_rows
    harness.set_weights.assert_not_called()
