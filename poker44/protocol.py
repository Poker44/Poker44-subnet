"""Bittensor protocol shared by Poker44 validators and miner axons."""

from __future__ import annotations

from typing import Any, ClassVar

import bittensor as bt
from pydantic import ConfigDict, Field


class SessionDetectionSynapse(bt.Synapse):
    """Classify miner-visible subject sessions as human or bot.

    Validators populate ``sessions`` and retain ground truth locally. Miners
    return one probability-like risk score for every session. A score close to
    zero means human and a score close to one means bot.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    protocol_version: str = "1"
    window_id: str = ""
    sessions: list[dict[str, Any]] = Field(default_factory=list)

    risk_scores: list[float] | None = None
    predictions: list[bool] | None = None
    model_version: str | None = None

    required_hash_fields: ClassVar[list[str]] = [
        "protocol_version",
        "window_id",
        "sessions",
    ]

    def deserialize(self) -> "SessionDetectionSynapse":
        return self


# Transitional import name for validators/miners that have not yet upgraded.
DetectionSynapse = SessionDetectionSynapse
