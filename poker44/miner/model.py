"""Stable model interface implemented by every Poker44 miner."""

from __future__ import annotations

from collections import Counter
from typing import Any, Protocol, runtime_checkable

from poker44.miner.config import MinerModelConfig


@runtime_checkable
class BotDetectionModel(Protocol):
    """A model resident in a miner process and served through its axon."""

    version: str

    def load(self) -> None: ...

    def predict(self, sessions: list[dict[str, Any]]) -> list[float]: ...


class ReferenceSessionModel:
    """Deterministic baseline using hands and interaction timing.

    This is intentionally only a runnable reference. Production miners provide
    their own factory through ``POKER44_MODEL_FACTORY``.
    """

    def __init__(self, config: MinerModelConfig):
        self.config = config
        self.version = config.version

    def load(self) -> None:
        return None

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @classmethod
    def _session_score(cls, session: dict[str, Any]) -> float:
        hands = session.get("hands") or []
        telemetry = session.get("telemetry") or {}
        events = telemetry.get("events") or []
        summary = telemetry.get("summary") or {}

        actions = [
            action
            for hand in hands
            for action in (hand.get("actions") or [])
            if isinstance(action, dict)
        ]
        counts = Counter(str(action.get("action_type") or "") for action in actions)
        meaningful = max(
            1,
            sum(counts[k] for k in ("fold", "check", "call", "bet", "raise", "all_in")),
        )
        aggression = (counts["bet"] + counts["raise"] + counts["all_in"]) / meaningful
        passive = (counts["check"] + counts["call"]) / meaningful

        decision_mean_ms = float(summary.get("decision_mean_ms") or 0.0)
        decision_std_ms = float(summary.get("decision_std_ms") or 0.0)
        client_events = sum(1 for event in events if event.get("source") == "client")
        event_density = client_events / max(1, len(hands))

        regularity = 1.0 - cls._clamp(decision_std_ms / 4000.0)
        fast_decisions = 1.0 - cls._clamp(decision_mean_ms / 5000.0)
        low_ui_activity = 1.0 - cls._clamp(event_density / 20.0)
        score = (
            0.35 * regularity
            + 0.25 * fast_decisions
            + 0.20 * low_ui_activity
            + 0.12 * cls._clamp(aggression / 0.45)
            + 0.08 * cls._clamp(passive / 0.70)
        )
        return round(cls._clamp(score), 6)

    def predict(self, sessions: list[dict[str, Any]]) -> list[float]:
        return [self._session_score(session) for session in sessions]


def create_reference_model(config: MinerModelConfig) -> BotDetectionModel:
    return ReferenceSessionModel(config)
