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
        if str(session.get("schema_version") or "") == "3":
            decisions = [
                decision
                for decision in (session.get("decisions") or [])
                if isinstance(decision, dict)
            ]
            counts = Counter(
                str(decision.get("action_type") or "") for decision in decisions
            )
            meaningful = max(1, len(decisions))
            aggression = (
                counts["bet"] + counts["raise"] + counts["all_in"]
            ) / meaningful
            passivity = (counts["check"] + counts["call"]) / meaningful
            folds = counts["fold"] / meaningful
            overbets = sum(
                1
                for decision in decisions
                if decision.get("size_bucket") in {"overbet", "all_in"}
            ) / meaningful
            score = (
                0.42 * cls._clamp(aggression / 0.45)
                + 0.24 * cls._clamp(folds / 0.45)
                + 0.20 * cls._clamp(overbets / 0.20)
                + 0.14 * (1.0 - cls._clamp(passivity / 0.75))
            )
            return round(cls._clamp(score), 6)

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
        # v1 exposed telemetry ``source`` while the sanitized tournament v2
        # contract removes it. When source is present, retain only client
        # events; otherwise every v2 event has already crossed the allowlist.
        sourced_events = [
            event for event in events if isinstance(event, dict) and "source" in event
        ]
        interaction_events = (
            sum(1 for event in sourced_events if event.get("source") == "client")
            if sourced_events
            else sum(1 for event in events if isinstance(event, dict))
        )
        event_density = interaction_events / max(1, len(hands))

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
