"""Query miner axons and calculate local rewards."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import socket
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import bittensor as bt
import numpy as np

from poker44.platform.models import ValidationRound
from poker44.utils.encrypted_endpoints import is_masked_axon
from poker44.validator.evaluation.models import MinerEvaluation
from poker44.validator.evaluation.redteam_gate import audit_redteam_leakage
from poker44.validator.evaluation.reward import reward
from poker44.validator.tracks import MICRO_SESSION_EVALUATION


class ValidatorEvaluationMixin:
    @staticmethod
    def _restore_evaluations(
        validation_round: ValidationRound,
    ) -> list[MinerEvaluation]:
        rows = validation_round.resume_evidence.get("evaluations")
        if validation_round.resume_state != "EVALUATED" or not isinstance(rows, list):
            return []
        restored: list[MinerEvaluation] = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("Stored evaluation evidence is malformed")
            restored.append(
                MinerEvaluation(
                    uid=int(row["uid"]),
                    hotkey=str(row["hotkey"]),
                    quality_score=float(row["quality_score"]),
                    metrics={
                        str(key): float(value)
                        for key, value in dict(row.get("metrics") or {}).items()
                    },
                    response_seconds=(
                        float(row["response_seconds"])
                        if row.get("response_seconds") is not None
                        else None
                    ),
                    model_version=(
                        str(row["model_version"])
                        if row.get("model_version") is not None
                        else None
                    ),
                    error=str(row["error"]) if row.get("error") is not None else None,
                )
            )
        if not restored:
            raise RuntimeError("Stored EVALUATED state has no miner evaluations")
        return restored

    def _candidate_miners(self, window_id: str) -> tuple[list[int], list[Any]]:
        try:
            overrides = json.loads(os.getenv("POKER44_AXON_OVERRIDES", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("POKER44_AXON_OVERRIDES must be valid JSON") from exc
        resolver = getattr(self, "endpoint_resolver", None)
        if resolver is not None:
            self.refresh_encrypted_endpoints()
        candidates: list[tuple[int, Any, bool]] = []
        for uid, axon in enumerate(self.metagraph.axons):
            if uid == int(self.uid):
                continue
            if bool(self.metagraph.validator_permit[uid]):
                continue
            override = str(overrides.get(str(uid), "")).strip()
            protected = False
            if override:
                host, override_port = override.rsplit(":", 1)
                axon = replace(
                    axon,
                    ip=socket.gethostbyname(host),
                    port=int(override_port),
                )
            elif resolver is not None:
                axon, protected = resolver.resolve(
                    self.metagraph.hotkeys[uid],
                    axon,
                )
            if is_masked_axon(axon) and not protected:
                bt.logging.warning(
                    f"Skipping protected miner UID {uid}: no decryptable endpoint is available."
                )
                continue
            ip = str(getattr(axon, "ip", "") or "")
            port = int(getattr(axon, "port", 0) or 0)
            if ip in {"", "0.0.0.0", "::", "[::]"} or port <= 0:
                continue
            candidates.append((uid, axon, protected))
        selected = sorted(candidates, key=lambda item: item[0])
        bt.logging.info(
            f"Selected all {len(selected)} eligible miner axons | "
            + ", ".join(
                f"uid={uid}@{'protected' if protected else f'{axon.ip}:{axon.port}'}"
                for uid, axon, protected in selected
            )
        )
        return [uid for uid, _, _ in selected], [axon for _, axon, _ in selected]

    @staticmethod
    def _response_seconds(response: Any) -> float | None:
        try:
            value = float(response.dendrite.process_time)
            return value if np.isfinite(value) and value >= 0.0 else None
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _align_responses(responses: list[Any], expected_count: int) -> list[Any]:
        aligned = list(responses[:expected_count])
        aligned.extend([None] * (expected_count - len(aligned)))
        return aligned

    def _evaluate_miner_responses(
        self,
        *,
        validation_round: ValidationRound,
        uids: list[int],
        responses: list[Any],
    ) -> list[MinerEvaluation]:
        evaluations: list[MinerEvaluation] = []
        allow_single_class = (
            os.getenv("POKER44_E2E_ALLOW_SINGLE_CLASS_REWARD", "false").lower()
            == "true"
        )
        for uid, response in zip(uids, responses):
            hotkey = str(self.metagraph.hotkeys[uid])
            try:
                raw_scores = getattr(response, "risk_scores", None)
                if not isinstance(raw_scores, list):
                    raise TypeError("missing risk_scores")
                scores = [float(value) for value in raw_scores]
                if len(scores) != len(validation_round.labels):
                    raise ValueError(
                        f"returned {len(scores)} scores for "
                        f"{len(validation_round.labels)} sessions"
                    )
                metrics = reward(
                    scores,
                    validation_round.labels,
                    sample_weights=validation_round.sample_weights,
                    allow_single_class=allow_single_class,
                )
                evaluation = MinerEvaluation(
                    uid=uid,
                    hotkey=hotkey,
                    quality_score=metrics.reward,
                    metrics=metrics.to_dict(),
                    response_seconds=self._response_seconds(response),
                    model_version=getattr(response, "model_version", None),
                )
            # A miner response must never abort evaluation of the remaining Axons.
            except Exception as exc:  # noqa: BLE001
                evaluation = MinerEvaluation(
                    uid=uid,
                    hotkey=hotkey,
                    quality_score=0.0,
                    metrics={},
                    response_seconds=self._response_seconds(response),
                    model_version=getattr(response, "model_version", None),
                    error=str(exc),
                )
            evaluations.append(evaluation)
        return evaluations

    @staticmethod
    def _write_miner_evaluations(
        *,
        round_id: str,
        stage: str,
        evaluations: list[MinerEvaluation],
        responses: list[Any],
        axons: list[Any],
    ) -> None:
        scores_path = Path(__file__).resolve().parents[3] / "scores.txt"
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        top_miner = (
            max(evaluations, key=lambda item: item.quality_score)
            if evaluations
            else None
        )
        axons_by_uid = {item.uid: axon for item, axon in zip(evaluations, axons)}
        lines = [
            "=" * 88,
            f"ROUND: {round_id}",
            f"DATE (UTC): {timestamp}",
            f"SNAPSHOT: {stage.replace('_', ' ').upper()}",
            "-" * 88,
            "TOP MINER",
        ]
        if top_miner is None:
            lines.append("  No miner evaluations available")
        else:
            top_axon = axons_by_uid.get(top_miner.uid)
            top_ip = str(getattr(top_axon, "ip", None))
            top_port = getattr(top_axon, "port", None)
            lines.extend(
                [
                    f"  UID: {top_miner.uid}",
                    f"  Hotkey: {top_miner.hotkey}",
                    f"  Endpoint: {top_ip}:{top_port}",
                    f"  Response time: {top_miner.response_seconds}s",
                    f"  Total score: {top_miner.quality_score:.6f}",
                    (
                        "  Score components: "
                        f"{json.dumps(top_miner.metrics, sort_keys=True)}"
                    ),
                ]
            )
        lines.extend(["-" * 88, "ALL MINERS"])
        for position, (item, response, axon) in enumerate(
            zip(evaluations, responses, axons), start=1
        ):
            status_code = getattr(
                getattr(response, "dendrite", None), "status_code", None
            )
            status_message = getattr(
                getattr(response, "dendrite", None), "status_message", None
            )
            ip = str(getattr(axon, "ip", None))
            port = getattr(axon, "port", None)
            lines.extend(
                [
                    f"  [{position}] UID {item.uid} | Hotkey: {item.hotkey}",
                    f"      Endpoint: {ip}:{port}",
                    f"      Total score: {item.quality_score:.6f}",
                    (
                        "      Score components: "
                        f"{json.dumps(item.metrics, sort_keys=True)}"
                    ),
                    (
                        f"      Response: {item.response_seconds}s | "
                        f"Model: {item.model_version}"
                    ),
                    (
                        f"      Status: {status_code} ({status_message}) | "
                        f"Error: {item.error}"
                    ),
                ]
            )
        lines.extend(["=" * 88, ""])
        descriptor = os.open(
            scores_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as scores_file:
            fcntl.flock(scores_file, fcntl.LOCK_EX)
            scores_file.write("\n".join(lines))
            scores_file.flush()
            fcntl.flock(scores_file, fcntl.LOCK_UN)

    @staticmethod
    def _log_miner_evaluations(
        *,
        stage: str,
        evaluations: list[MinerEvaluation],
        responses: list[Any],
    ) -> None:
        successful = sum(item.error is None for item in evaluations)
        bt.logging.info(
            "Miner evaluation summary | "
            f"stage={stage} successful={successful}/{len(evaluations)} "
            f"failed={len(evaluations) - successful}"
        )
        for item, response in zip(evaluations, responses):
            status_code = getattr(
                getattr(response, "dendrite", None), "status_code", None
            )
            status = "OK" if item.error is None else "FAILED"
            bt.logging.info(
                f"  {'✓' if item.error is None else '✗'} UID {item.uid:<4} "
                f"{status:<6} | score={item.quality_score:.6f} "
                f"response={item.response_seconds}s model={item.model_version} "
                f"http={status_code} error={item.error or '-'}"
            )

    @staticmethod
    async def _wait_before_miner_retry(
        *, uids: list[int], responses: list[Any]
    ) -> None:
        missing_uids = [
            uid
            for uid, response in zip(uids, responses)
            if not isinstance(getattr(response, "risk_scores", None), list)
        ]
        if not missing_uids:
            return

        delay = max(
            0.0,
            float(os.getenv("POKER44_MINER_RETRY_DELAY_SECONDS", "120")),
        )
        bt.logging.warning(
            "Waiting before logging scores and retrying transient miners | "
            f"uids={','.join(str(uid) for uid in missing_uids)} "
            f"delay_seconds={delay:g}"
        )
        if delay:
            await asyncio.sleep(delay)

    async def _retry_transient_responses(
        self,
        *,
        uids: list[int],
        axons: list[Any],
        synapse: bt.Synapse,
        responses: list[Any],
    ) -> list[Any]:
        """Retry miners that returned no scores before finalizing the round."""

        missing = [
            index
            for index, response in enumerate(responses)
            if not isinstance(getattr(response, "risk_scores", None), list)
        ]
        if not missing:
            return responses

        bt.logging.warning(
            "Retrying transient miner responses | "
            f"uids={','.join(str(uids[index]) for index in missing)}"
        )
        retried = await self.dendrite(
            axons=[axons[index] for index in missing],
            synapse=synapse,
            deserialize=False,
            timeout=float(self.config.neuron.timeout),
        )
        merged = list(responses)
        for index, response in zip(missing, retried):
            merged[index] = response
        return merged

    async def _run_evaluation_phase(
        self, validation_round: ValidationRound
    ) -> list[MinerEvaluation]:
        restored = ValidatorEvaluationMixin._restore_evaluations(validation_round)
        if restored:
            bt.logging.info(
                "Resuming durable evaluated round without querying miners | "
                f"window={validation_round.lease.window_id} miners={len(restored)}"
            )
            return restored
        redteam_threshold = float(os.getenv("POKER44_REDTEAM_MAX_REWARD", "0.15"))
        redteam = audit_redteam_leakage(
            validation_round.miner_items,
            validation_round.labels,
            threshold=redteam_threshold,
        )
        await self._report_event(
            "redteam_gate_checked",
            validation_round,
            redteam.to_dict(),
        )
        enforce_redteam = (
            os.getenv("POKER44_ENFORCE_REDTEAM_GATE", "true").lower() == "true"
        )
        if (
            redteam.skipped
            and os.getenv("POKER44_E2E_ALLOW_SINGLE_CLASS_REWARD", "false").lower()
            != "true"
        ):
            raise RuntimeError("Red-team gate requires a mixed human/bot window")
        if enforce_redteam and not redteam.skipped and not redteam.passed:
            raise RuntimeError(
                "Red-team leakage gate failed: "
                f"feature={redteam.feature} reward={redteam.reward:.6f} "
                f"threshold={redteam.threshold:.6f}"
            )

        uids, axons = self._candidate_miners(validation_round.lease.window_id)
        if not uids:
            bt.logging.warning("No reachable miner axons were found")
            return []
        bt.logging.info("╔════════ Poker44 validator · miner evaluation ════════╗")
        bt.logging.info(
            "║ Preparing evaluation batch | "
            f"round={validation_round.round_id} "
            f"window={validation_round.lease.window_id} "
            f"miners={len(uids)} items={len(validation_round.labels)}"
        )
        bt.logging.info("╚════════ Sending the first request batch to miners ═══╝")
        synapse = MICRO_SESSION_EVALUATION.build_synapse(
            validation_round,
            self.wallet.hotkey.ss58_address,
        )
        responses = list(
            await self.dendrite(
                axons=axons,
                synapse=synapse,
                deserialize=False,
                timeout=float(self.config.neuron.timeout),
            )
        )
        responses = self._align_responses(responses, len(uids))
        initial_evaluations = self._evaluate_miner_responses(
            validation_round=validation_round,
            uids=uids,
            responses=responses,
        )
        initial_successes = sum(item.error is None for item in initial_evaluations)
        bt.logging.info(
            "✓ First miner request batch finished | "
            f"responses={len(responses)}/{len(uids)} "
            f"valid={initial_successes} retry_candidates="
            f"{len(initial_evaluations) - initial_successes}"
        )
        self._log_miner_evaluations(
            stage="before_retry",
            evaluations=initial_evaluations,
            responses=responses,
        )
        await self._wait_before_miner_retry(uids=uids, responses=responses)
        bt.logging.info(
            "→ Writing pre-retry miner scores | "
            f"round={validation_round.round_id} file=scores.txt"
        )
        self._write_miner_evaluations(
            round_id=validation_round.round_id,
            stage="before_retry",
            evaluations=initial_evaluations,
            responses=responses,
            axons=axons,
        )
        bt.logging.info("✓ Pre-retry scores appended to scores.txt")
        responses = await self._retry_transient_responses(
            uids=uids,
            axons=axons,
            synapse=synapse,
            responses=responses,
        )
        evaluations = self._evaluate_miner_responses(
            validation_round=validation_round,
            uids=uids,
            responses=responses,
        )
        self._log_miner_evaluations(
            stage="final",
            evaluations=evaluations,
            responses=responses,
        )
        bt.logging.info(
            "→ Writing final miner scores | "
            f"round={validation_round.round_id} file=scores.txt"
        )
        self._write_miner_evaluations(
            round_id=validation_round.round_id,
            stage="after_retry",
            evaluations=evaluations,
            responses=responses,
            axons=axons,
        )
        final_successes = sum(item.error is None for item in evaluations)
        bt.logging.info("╔════════ Miner evaluation complete ═══════════════════╗")
        bt.logging.info(
            "║ Final result | "
            f"successful={final_successes}/{len(evaluations)} "
            f"failed={len(evaluations) - final_successes} "
            "scores_file=scores.txt"
        )
        bt.logging.info("╚════════ Continuing to rewards and settlement ═══════╝")
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
        advanced = await asyncio.to_thread(
            self.subnet_data.advance_evaluation_run,
            validation_round.lease.window_id,
            validation_round.round_id,
            "EVALUATED",
            {
                "miner_count": len(evaluations),
                "item_count": len(validation_round.labels),
                "query_id": str(getattr(synapse, "query_id", "")),
                "evaluations": [
                    {
                        "uid": item.uid,
                        "hotkey": item.hotkey,
                        "quality_score": item.quality_score,
                        "metrics": item.metrics,
                        "response_seconds": item.response_seconds,
                        "model_version": item.model_version,
                        "error": item.error,
                    }
                    for item in evaluations
                ],
            },
        )
        if not advanced:
            raise RuntimeError("Could not persist EVALUATED state")
        return evaluations
