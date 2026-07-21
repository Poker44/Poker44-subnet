"""Validation and execution around a miner-owned inference model."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
from typing import Any

from poker44.miner.config import MinerModelConfig
from poker44.miner.model import BotDetectionModel


class MinerInferenceService:
    def __init__(self, model: BotDetectionModel, config: MinerModelConfig):
        self.model = model
        self.config = config
        self._model_lock = asyncio.Lock()

    @staticmethod
    def _find_forbidden(value: Any, path: str = "session") -> list[str]:
        forbidden = {"is_bot", "is_human", "ground_truth", "label", "bot_family"}
        leaked: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if str(key).lower() in forbidden:
                    leaked.append(child_path)
                leaked.extend(MinerInferenceService._find_forbidden(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                leaked.extend(
                    MinerInferenceService._find_forbidden(child, f"{path}[{index}]")
                )
        return leaked

    @staticmethod
    def _validate_session(session: Any, index: int) -> dict[str, Any]:
        if not isinstance(session, dict):
            raise ValueError(f"sessions[{index}] must be an object")
        if str(session.get("schema_version") or "") != "1":
            raise ValueError(f"sessions[{index}] has unsupported schema_version")
        if not str(session.get("session_id") or "").strip():
            raise ValueError(f"sessions[{index}] has no session_id")
        hands = session.get("hands")
        if not isinstance(hands, list) or not hands:
            raise ValueError(f"sessions[{index}] must contain at least one hand")
        telemetry = session.get("telemetry")
        if not isinstance(telemetry, dict):
            raise ValueError(f"sessions[{index}] has invalid telemetry")
        leaked = MinerInferenceService._find_forbidden(session, f"sessions[{index}]")
        if leaked:
            raise ValueError(
                f"sessions[{index}] contains ground-truth fields: {sorted(leaked)}"
            )
        return session

    async def predict(self, sessions: list[dict[str, Any]]) -> list[float]:
        if not sessions:
            raise ValueError("A detection request must contain at least one session")
        if len(sessions) > self.config.max_sessions_per_request:
            raise ValueError(
                f"Request contains {len(sessions)} sessions; maximum is "
                f"{self.config.max_sessions_per_request}"
            )
        request_bytes = len(
            json.dumps(sessions, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        if request_bytes > self.config.max_request_bytes:
            raise ValueError(
                f"Request is {request_bytes} bytes; maximum is "
                f"{self.config.max_request_bytes}"
            )
        validated = [
            self._validate_session(session, i) for i, session in enumerate(sessions)
        ]
        async with self._model_lock:
            if inspect.iscoroutinefunction(self.model.predict):
                result = await self.model.predict(validated)
            else:
                result = await asyncio.to_thread(self.model.predict, validated)
        if inspect.isawaitable(result):
            result = await result
        scores = [float(score) for score in result]
        if len(scores) != len(validated):
            raise ValueError(
                f"Model returned {len(scores)} scores for {len(validated)} sessions"
            )
        if any(
            not math.isfinite(score) or score < 0.0 or score > 1.0 for score in scores
        ):
            raise ValueError("Model risk scores must be finite values within [0, 1]")
        return scores
