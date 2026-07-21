"""Query miner axons and calculate local rewards."""

from __future__ import annotations

import os
import json
import socket
from hashlib import sha256
from dataclasses import replace
from typing import Any

import bittensor as bt
import numpy as np

from poker44.platform.models import ValidationRound
from poker44.protocol import SessionDetectionSynapse
from poker44.validator.evaluation.models import MinerEvaluation
from poker44.validator.evaluation.reward import reward


class ValidatorEvaluationMixin:
    def _candidate_miners(self, window_id: str) -> tuple[list[int], list[Any]]:
        limit = max(1, int(os.getenv("POKER44_MINERS_PER_ROUND", "32")))
        try:
            overrides = json.loads(os.getenv("POKER44_AXON_OVERRIDES", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("POKER44_AXON_OVERRIDES must be valid JSON") from exc
        candidates: list[tuple[int, Any]] = []
        for uid, axon in enumerate(self.metagraph.axons):
            if uid == int(self.uid):
                continue
            if bool(self.metagraph.validator_permit[uid]):
                continue
            override = str(overrides.get(str(uid), "")).strip()
            if override:
                host, override_port = override.rsplit(":", 1)
                axon = replace(
                    axon,
                    ip=socket.gethostbyname(host),
                    port=int(override_port),
                )
            ip = str(getattr(axon, "ip", "") or "")
            port = int(getattr(axon, "port", 0) or 0)
            if ip in {"", "0.0.0.0", "::", "[::]"} or port <= 0:
                continue
            candidates.append((uid, axon))
        validator_hotkey = str(self.wallet.hotkey.ss58_address)
        candidates.sort(
            key=lambda item: sha256(
                f"{window_id}:{validator_hotkey}:{item[0]}:{self.metagraph.hotkeys[item[0]]}".encode()
            ).digest()
        )
        selected = candidates[:limit]
        bt.logging.info(
            "Selected miner axons | "
            + ", ".join(f"uid={uid}@{axon.ip}:{axon.port}" for uid, axon in selected)
        )
        return [uid for uid, _ in selected], [axon for _, axon in selected]

    @staticmethod
    def _response_seconds(response: Any) -> float | None:
        try:
            value = float(response.dendrite.process_time)
            return value if np.isfinite(value) and value >= 0.0 else None
        except Exception:
            return None

    async def _run_evaluation_phase(
        self, validation_round: ValidationRound
    ) -> list[MinerEvaluation]:
        uids, axons = self._candidate_miners(validation_round.lease.window_id)
        if not uids:
            bt.logging.warning("No reachable miner axons were found")
            return []
        synapse = SessionDetectionSynapse(
            window_id=validation_round.lease.window_id,
            sessions=validation_round.miner_sessions,
        )
        responses = await self.dendrite(
            axons=axons,
            synapse=synapse,
            deserialize=False,
            timeout=float(self.config.neuron.timeout),
        )
        evaluations: list[MinerEvaluation] = []
        for uid, response in zip(uids, responses):
            hotkey = str(self.metagraph.hotkeys[uid])
            try:
                raw_scores = getattr(response, "risk_scores", None)
                if not isinstance(raw_scores, list):
                    raise ValueError("missing risk_scores")
                scores = [float(value) for value in raw_scores]
                if len(scores) != len(validation_round.labels):
                    raise ValueError(
                        f"returned {len(scores)} scores for {len(validation_round.labels)} sessions"
                    )
                metrics = reward(
                    scores,
                    validation_round.labels,
                    allow_single_class=os.getenv(
                        "POKER44_E2E_ALLOW_SINGLE_CLASS_REWARD", "false"
                    ).lower()
                    == "true",
                )
                evaluations.append(
                    MinerEvaluation(
                        uid=uid,
                        hotkey=hotkey,
                        reward=metrics.reward,
                        metrics=metrics.to_dict(),
                        response_seconds=self._response_seconds(response),
                        model_version=getattr(response, "model_version", None),
                    )
                )
            except Exception as exc:
                evaluations.append(
                    MinerEvaluation(
                        uid=uid,
                        hotkey=hotkey,
                        reward=0.0,
                        metrics={},
                        response_seconds=self._response_seconds(response),
                        model_version=getattr(response, "model_version", None),
                        error=str(exc),
                    )
                )
            item = evaluations[-1]
            status_code = getattr(
                getattr(response, "dendrite", None), "status_code", None
            )
            status_message = getattr(
                getattr(response, "dendrite", None), "status_message", None
            )
            bt.logging.info(
                "Miner evaluation | "
                f"uid={uid} reward={item.reward:.6f} model={item.model_version} "
                f"status={status_code} message={status_message} error={item.error}"
            )
        await self._report_event(
            "miners_queried",
            validation_round,
            {
                "miner_count": len(evaluations),
                "miners": [
                    {
                        "uid": item.uid,
                        "hotkey": item.hotkey,
                        "response_seconds": item.response_seconds,
                        "model_version": item.model_version,
                        "error": item.error,
                    }
                    for item in evaluations
                ],
            },
        )
        await self._report_event(
            "rewards_computed",
            validation_round,
            {
                "rewards": [
                    {
                        "uid": item.uid,
                        "hotkey": item.hotkey,
                        "reward": item.reward,
                        "metrics": item.metrics,
                        "model_version": item.model_version,
                    }
                    for item in evaluations
                ]
            },
        )
        return evaluations
