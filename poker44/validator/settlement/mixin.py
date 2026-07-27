"""Update local score state and publish weights when the chain cadence allows."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import bittensor as bt
import numpy as np

from poker44.platform.models import ValidationRound
from poker44.validator.evaluation.models import MinerEvaluation
from poker44.validator.settlement.weights import weight_rows


class ValidatorSettlementMixin:
    def _pending_reveal_state_path(self) -> Path:
        configured = os.getenv("POKER44_PENDING_REVEALS_PATH", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path(self.config.neuron.full_path) / "pending_weight_reveals.json"

    def _load_pending_reveal_reports(self) -> list[dict]:
        path = self._pending_reveal_state_path()
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, list):
                raise ValueError("pending reveal state must be a list")
            return [item for item in value if isinstance(item, dict)]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            bt.logging.warning(f"Could not read pending weight reveal state: {exc}")
            return []

    def _save_pending_reveal_reports(self, reports: list[dict]) -> None:
        path = self._pending_reveal_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(reports, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)

    def _record_pending_reveal(
        self,
        validation_round: ValidationRound,
        weights: list[dict],
        evidence: dict,
    ) -> None:
        reports = self._load_pending_reveal_reports()
        record = {
            "round_id": validation_round.round_id,
            "weights": weights,
            "commit_block": int(evidence["commit_block"]),
            "reveal_round": int(evidence["reveal_round"]),
        }
        key = (record["commit_block"], record["reveal_round"])
        reports = [
            item
            for item in reports
            if (item.get("commit_block"), item.get("reveal_round")) != key
        ]
        reports.append(record)
        self._save_pending_reveal_reports(reports)

    async def _pending_weight_commits(self) -> list[dict]:
        commits = await asyncio.to_thread(
            self.subtensor.get_timelocked_weight_commits, self.config.netuid
        )
        return [
            {
                "hotkey": str(hotkey),
                "commit_block": int(commit_block),
                "reveal_round": int(reveal_round),
            }
            for hotkey, commit_block, _ciphertext, reveal_round in commits
            if str(hotkey) == self.wallet.hotkey.ss58_address
        ]

    async def _weight_update_visible_after(self, commit_block: int) -> bool:
        metagraph = await asyncio.to_thread(
            self.subtensor.metagraph, self.config.netuid
        )
        hotkey = self.wallet.hotkey.ss58_address
        try:
            uid = list(metagraph.hotkeys).index(hotkey)
        except ValueError:
            return False
        return int(metagraph.last_update[uid]) > int(commit_block)

    async def _reconcile_pending_weight_reveals(self) -> None:
        reports = self._load_pending_reveal_reports()
        if not reports:
            return
        pending = {
            (item["commit_block"], item["reveal_round"])
            for item in await self._pending_weight_commits()
        }
        remaining: list[dict] = []
        for report in reports:
            key = (int(report["commit_block"]), int(report["reveal_round"]))
            if key in pending or not await self._weight_update_visible_after(key[0]):
                remaining.append(report)
                continue
            await self._report_event(
                "weights_revealed",
                SimpleNamespace(round_id=str(report["round_id"])),
                {
                    "weights": report["weights"],
                    "commit_reveal": True,
                    "commit_block": key[0],
                    "reveal_round": key[1],
                    "chain_state": "weights_visible",
                    "finalized_scope": "weights",
                },
            )
            bt.logging.info(
                "Committed weights are now visible on-chain | "
                f"round={report['round_id']} commit_block={key[0]}"
            )
        self._save_pending_reveal_reports(remaining)

    async def _wait_for_testnet_weight_rate_limit(self) -> None:
        """Wait for the chain cadence when a test validation_round forces submission."""
        hyperparameters = await asyncio.to_thread(
            self.subtensor.get_subnet_hyperparameters, self.config.netuid
        )
        rate_limit = int(getattr(hyperparameters, "weights_rate_limit", 0) or 0)
        last_update = int(self.metagraph.last_update[self.uid])
        while rate_limit > 0:
            current_block = int(
                await asyncio.to_thread(self.subtensor.get_current_block)
            )
            # SDK 10 requires blocks_since_last_update > weights_rate_limit.
            remaining = (rate_limit + 1) - (current_block - last_update)
            if remaining <= 0:
                return
            bt.logging.info(
                "Waiting for testnet weight rate limit | "
                f"current_block={current_block} last_update={last_update} "
                f"remaining_blocks={remaining}"
            )
            await asyncio.sleep(min(30, max(6, remaining * 12)))

    async def _run_settlement_phase(
        self, validation_round: ValidationRound, evaluations: list[MinerEvaluation]
    ) -> dict:
        if evaluations:
            self.update_scores(
                np.asarray([item.reward for item in evaluations], dtype=np.float32),
                [item.uid for item in evaluations],
            )
        prepared_weights = await asyncio.to_thread(self.prepare_weights)
        weights = weight_rows(prepared_weights)
        for row in weights:
            row["hotkey"] = str(self.metagraph.hotkeys[int(row["uid"])])
        await self._report_event("weights_computed", validation_round, {"weights": weights})

        submitted = False
        force_test_weights = (
            os.getenv("POKER44_FORCE_SET_WEIGHTS", "false").lower() == "true"
        )
        if force_test_weights or self.should_set_weights():
            if force_test_weights:
                await self._wait_for_testnet_weight_rate_limit()
            commit_reveal = bool(
                await asyncio.to_thread(
                    self.subtensor.commit_reveal_enabled, self.config.netuid
                )
            )
            commits_before = (
                await self._pending_weight_commits() if commit_reveal else []
            )
            submitted = bool(
                await asyncio.to_thread(self.set_weights, prepared_weights)
            )
            if not submitted:
                raise RuntimeError("Validator weight submission failed")
            evidence: dict = {"commit_reveal": commit_reveal}
            if commit_reveal:
                previous_block = max(
                    (item["commit_block"] for item in commits_before), default=-1
                )
                commits_after = await self._pending_weight_commits()
                new_commits = [
                    item
                    for item in commits_after
                    if item["commit_block"] > previous_block
                ]
                if not new_commits:
                    raise RuntimeError(
                        "Weight extrinsic returned success but no new on-chain commit was found"
                    )
                evidence.update(new_commits[-1])
                evidence["chain_state"] = "committed_pending_reveal"
                self._record_pending_reveal(validation_round, weights, evidence)
            else:
                evidence["chain_state"] = "weights_visible"
            await self._report_event(
                "weights_submitted", validation_round, {"weights": weights, **evidence}
            )
            if bool(self.config.neuron.wait_for_finalization):
                await self._report_event(
                    "weights_finalized",
                    validation_round,
                    {
                        "weights": weights,
                        **evidence,
                        "finalized_scope": "commit_extrinsic"
                        if commit_reveal
                        else "weights",
                    },
                )
        return {"weights": weights, "submitted": submitted}
