"""Update local score state and publish weights when the chain cadence allows."""

from __future__ import annotations

import asyncio
import os

import bittensor as bt
import numpy as np

from poker44.platform.models import ValidationRound
from poker44.validator.evaluation.models import MinerEvaluation
from poker44.validator.settlement.weights import weight_rows


class ValidatorSettlementMixin:
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
