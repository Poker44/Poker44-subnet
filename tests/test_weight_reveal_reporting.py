from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from poker44.validator.settlement.mixin import ValidatorSettlementMixin


class FakeSubtensor:
    def __init__(self, hotkey: str):
        self.hotkey = hotkey
        self.pending = []

    def get_timelocked_weight_commits(self, _netuid):
        return self.pending

    def metagraph(self, _netuid):
        return SimpleNamespace(hotkeys=[self.hotkey], last_update=[120])

    def weights(self, _netuid):
        return [(0, [(2, 65535)])]


@pytest.mark.asyncio
async def test_pending_weight_reveal_is_reported_after_becoming_visible(tmp_path):
    hotkey = "validator-hotkey"
    validator = object.__new__(ValidatorSettlementMixin)
    validator.config = SimpleNamespace(
        netuid=492,
        neuron=SimpleNamespace(full_path=str(tmp_path)),
    )
    validator.wallet = SimpleNamespace(
        hotkey=SimpleNamespace(ss58_address=hotkey)
    )
    validator.uid = 0
    validator.subtensor = FakeSubtensor(hotkey)
    validator._report_event = AsyncMock()
    validation_round = SimpleNamespace(round_id="window-1")
    weights = [{"uid": 2, "hotkey": "miner-hotkey", "weight": 1.0}]

    validator._record_pending_reveal(
        validation_round,
        weights,
        {"commit_block": 100, "reveal_round": 200},
    )
    state_path = validator._pending_reveal_state_path()
    assert state_path.stat().st_mode & 0o777 == 0o600

    await validator._reconcile_pending_weight_reveals()

    validator._report_event.assert_awaited_once()
    event_type, reported_round, payload = validator._report_event.await_args.args
    assert event_type == "weights_revealed"
    assert reported_round.round_id == "window-1"
    assert payload["chain_state"] == "weights_visible"
    assert payload["finalized_scope"] == "weights"
    assert validator._load_pending_reveal_reports() == []


@pytest.mark.asyncio
async def test_pending_weight_reveal_stays_queued_while_commit_is_pending(tmp_path):
    hotkey = "validator-hotkey"
    validator = object.__new__(ValidatorSettlementMixin)
    validator.config = SimpleNamespace(
        netuid=492,
        neuron=SimpleNamespace(full_path=str(tmp_path)),
    )
    validator.wallet = SimpleNamespace(
        hotkey=SimpleNamespace(ss58_address=hotkey)
    )
    validator.uid = 0
    validator.subtensor = FakeSubtensor(hotkey)
    validator.subtensor.pending = [(hotkey, 100, b"ciphertext", 200)]
    validator._report_event = AsyncMock()

    validator._record_pending_reveal(
        SimpleNamespace(round_id="window-1"),
        [{"uid": 2, "hotkey": "miner-hotkey", "weight": 1.0}],
        {"commit_block": 100, "reveal_round": 200},
    )

    await validator._reconcile_pending_weight_reveals()

    validator._report_event.assert_not_awaited()
    assert len(validator._load_pending_reveal_reports()) == 1
