"""Query miner axons and calculate local rewards."""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
from dataclasses import replace
from hashlib import sha256
from typing import Any

import bittensor as bt
import numpy as np

from poker44.platform.models import ValidationRound
from poker44.protocol import SessionDetectionSynapse
from poker44.validator.evaluation.models import MinerEvaluation
from poker44.validator.evaluation.redteam_gate import audit_redteam_leakage
from poker44.validator.evaluation.reward import reward
from poker44.utils.encrypted_endpoints import is_masked_axon


class ValidatorEvaluationMixin:
    def _candidate_miners(self, window_id: str) -> tuple[list[int], list[Any]]:
        limit = max(1, int(os.getenv("POKER44_MINERS_PER_ROUND", "32")))
        try:
            overrides = json.loads(os.getenv("POKER44_AXON_OVERRIDES", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("POKER44_AXON_OVERRIDES must be valid JSON") from exc
        try:
            identities = json.loads(os.getenv("POKER44_MINER_IDENTITIES_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                "POKER44_MINER_IDENTITIES_JSON must be valid JSON"
            ) from exc
        require_identity = (
            os.getenv("POKER44_REQUIRE_MINER_IDENTITY", "true").lower() == "true"
        )
        fixture_uids = {
            int(value)
            for value in os.getenv("POKER44_TEST_FIXTURE_UIDS", "").split(",")
            if value.strip().isdigit()
        }
        allow_fixture_shared_coldkey = (
            os.getenv("POKER44_TEST_FIXTURE_ALLOW_SHARED_COLDKEY", "false").lower()
            == "true"
        )
        resolver = getattr(self, "endpoint_resolver", None)
        if resolver is not None:
            self.refresh_encrypted_endpoints()
        candidates: list[tuple[int, Any, bool]] = []
        seen_coldkeys: set[str] = set()
        seen_repositories: set[str] = set()
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
            hotkey = str(self.metagraph.hotkeys[uid])
            coldkey = str(self.metagraph.coldkeys[uid])
            coldkey_identity = (
                f"test-fixture://uid-{uid}"
                if uid in fixture_uids and allow_fixture_shared_coldkey
                else coldkey
            )
            identity = identities.get(hotkey)
            if require_identity:
                if uid in fixture_uids:
                    # Explicit testnet-only fixtures exercise validator scoring
                    # without pretending that synthetic local miners own a
                    # public GitHub repository.
                    repository = f"test-fixture://uid-{uid}"
                elif not isinstance(identity, dict):
                    bt.logging.warning(
                        f"Skipping uid={uid}: no verified miner identity"
                    )
                    continue
                else:
                    repository = (
                        str(identity.get("repository_url", ""))
                        .lower()
                        .removesuffix(".git")
                        .rstrip("/")
                    )
                    commit = str(identity.get("repository_commit", "")).lower()
                    if not re.fullmatch(
                        r"https://github\.com/[a-z0-9_.-]+/[a-z0-9_.-]+", repository
                    ) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                        bt.logging.warning(
                            f"Skipping uid={uid}: invalid GitHub repository proof"
                        )
                        continue
                if repository in seen_repositories:
                    bt.logging.warning(f"Skipping uid={uid}: repository already used")
                    continue
                seen_repositories.add(repository)
            if coldkey_identity in seen_coldkeys:
                bt.logging.warning(f"Skipping uid={uid}: coldkey already represented")
                continue
            seen_coldkeys.add(coldkey_identity)
            candidates.append((uid, axon, protected))
        validator_hotkey = str(self.wallet.hotkey.ss58_address)
        candidates.sort(
            key=lambda item: sha256(
                f"{window_id}:{validator_hotkey}:{item[0]}:{self.metagraph.hotkeys[item[0]]}".encode()
            ).digest()
        )
        selected = candidates[:limit]
        bt.logging.info(
            "Selected miner axons | "
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
        except Exception:
            return None

    async def _retry_transient_responses(
        self,
        *,
        uids: list[int],
        axons: list[Any],
        synapse: SessionDetectionSynapse,
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

        delay = max(
            0.0, float(os.getenv("POKER44_MINER_RETRY_DELAY_SECONDS", "30"))
        )
        bt.logging.warning(
            "Retrying transient miner responses | "
            f"uids={','.join(str(uids[index]) for index in missing)} "
            f"delay_seconds={delay:g}"
        )
        if delay:
            await asyncio.sleep(delay)
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
        redteam_threshold = float(os.getenv("POKER44_REDTEAM_MAX_REWARD", "0.15"))
        redteam = audit_redteam_leakage(
            validation_round.miner_sessions,
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
            and os.getenv(
                "POKER44_E2E_ALLOW_SINGLE_CLASS_REWARD", "false"
            ).lower()
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
        synapse = SessionDetectionSynapse(
            window_id=validation_round.lease.window_id,
            dataset_hash=validation_round.lease.dataset_hash,
            sessions=validation_round.miner_sessions,
        )
        responses = await self.dendrite(
            axons=axons,
            synapse=synapse,
            deserialize=False,
            timeout=float(self.config.neuron.timeout),
        )
        responses = await self._retry_transient_responses(
            uids=uids,
            axons=axons,
            synapse=synapse,
            responses=responses,
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
