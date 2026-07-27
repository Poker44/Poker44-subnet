from types import SimpleNamespace

from poker44.validator.evaluation.mixin import ValidatorEvaluationMixin


class Harness(ValidatorEvaluationMixin):
    def __init__(self):
        self.uid = 0
        self.wallet = SimpleNamespace(hotkey=SimpleNamespace(ss58_address="validator"))
        self.metagraph = SimpleNamespace(
            axons=[
                SimpleNamespace(ip="127.0.0.1", port=9000),
                SimpleNamespace(ip="127.0.0.1", port=9001),
                SimpleNamespace(ip="127.0.0.1", port=9002),
                SimpleNamespace(ip="127.0.0.1", port=9003),
            ],
            hotkeys=["validator", "miner-a", "miner-b", "miner-c"],
            coldkeys=["validator-cold", "same-cold", "same-cold", "other-cold"],
            validator_permit=[True, False, False, False],
        )


def test_candidate_selection_enforces_one_hotkey_per_coldkey_and_identity(monkeypatch):
    monkeypatch.setenv("POKER44_REQUIRE_MINER_IDENTITY", "true")
    monkeypatch.setenv("POKER44_TEST_FIXTURE_UIDS", "1,2")
    monkeypatch.delenv("POKER44_MINER_IDENTITIES_JSON", raising=False)

    uids, _ = Harness()._candidate_miners("window-1")

    assert uids == [1]


def test_explicit_fixture_mode_can_represent_synthetic_shared_coldkeys(monkeypatch):
    monkeypatch.setenv("POKER44_REQUIRE_MINER_IDENTITY", "true")
    monkeypatch.setenv("POKER44_TEST_FIXTURE_UIDS", "1,2")
    monkeypatch.setenv("POKER44_TEST_FIXTURE_ALLOW_SHARED_COLDKEY", "true")
    monkeypatch.delenv("POKER44_MINER_IDENTITIES_JSON", raising=False)

    uids, _ = Harness()._candidate_miners("window-1")

    assert set(uids) == {1, 2}
