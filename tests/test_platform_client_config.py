from poker44.platform.client import SubnetDataConfig


def test_standard_tournament_window_is_the_default(monkeypatch):
    monkeypatch.delenv("POKER44_VALIDATOR_SESSIONS_PER_ROUND", raising=False)

    config = SubnetDataConfig.from_env()

    assert config.requested_sessions == 20


def test_standard_tournament_window_can_be_overridden(monkeypatch):
    monkeypatch.setenv("POKER44_VALIDATOR_SESSIONS_PER_ROUND", "40")

    config = SubnetDataConfig.from_env()

    assert config.requested_sessions == 40
