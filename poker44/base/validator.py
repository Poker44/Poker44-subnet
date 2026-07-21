# The MIT License (MIT)
# Copyright (c) 2025 apaor

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


import copy
import os
import numpy as np
import asyncio
import argparse
import threading
import time
import bittensor as bt
from typing import List, Union
from traceback import print_exception
from poker44.base.neuron import BaseNeuron
from poker44.base.utils.weight_utils import (
    process_weights_for_netuid,
    convert_weights_and_uids_for_emit,
)
from poker44.utils.config import add_validator_args
from poker44.validator.settlement.weights import retain_top_scores


class BaseValidatorNeuron(BaseNeuron):
    """
    Base class for Bittensor validators. Your validator should inherit from this class.
    """

    neuron_type: str = "ValidatorNeuron"

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        super().add_args(parser)
        add_validator_args(cls, parser)

    def __init__(self, config=None):
        super().__init__(config=config)

        # Save a copy of the hotkeys to local memory.
        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

        self.dendrite = bt.Dendrite(wallet=self.wallet)

        bt.logging.info(f"Dendrite: {self.dendrite}")

        # Set up initial scoring weights for validation
        bt.logging.info("Building validation weights.")
        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
        self.axon = None

        # Restore EMA scores by hotkey identity. UIDs can be reassigned between
        # restarts, so an index-only restore would credit the wrong miner.
        self.load_state()

        # Serve axon to enable external connections.
        if not self.config.neuron.axon_off:
            self.serve_axon()
        else:
            bt.logging.warning("axon off, not serving ip to chain.")

        # Create asyncio event loop to manage async tasks.
        self.loop = asyncio.get_event_loop()

        # Instantiate runners
        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: Union[threading.Thread, None] = None
        self.lock = asyncio.Lock()

    def serve_axon(self):
        """Serve axon to enable external connections."""

        bt.logging.info("serving ip to chain...")
        try:
            self.axon = bt.Axon(wallet=self.wallet, config=self.config)

            try:
                self.subtensor.serve_axon(
                    netuid=self.config.netuid,
                    axon=self.axon,
                )
                bt.logging.info(
                    f"Running validator {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid: {self.config.netuid}"
                )
            except Exception as e:
                bt.logging.error(f"Failed to serve Axon with exception: {e}")
                pass

        except Exception as e:
            bt.logging.error(f"Failed to create Axon initialize with exception: {e}")
            pass

    async def concurrent_forward(self):
        coroutines = [
            self.forward() for _ in range(self.config.neuron.num_concurrent_forwards)
        ]
        await asyncio.gather(*coroutines)

    def run(self):
        """
        Initiates and manages the main loop for the miner on the Bittensor network. The main loop handles graceful shutdown on keyboard interrupts and logs unforeseen errors.

        This function performs the following primary tasks:
        1. Check for registration on the Bittensor network.
        2. Continuously forwards queries to the miners on the network, rewarding their responses and updating the scores accordingly.
        3. Periodically resynchronizes with the chain; updating the metagraph with the latest network state and setting weights.

        The essence of the validator's operations is in the forward function, which is called every step. The forward function is responsible for querying the network and scoring the responses.

        Note:
            - The function leverages the global configurations set during the initialization of the miner.
            - The miner's axon serves as its interface to the Bittensor network, handling incoming and outgoing requests.

        Raises:
            KeyboardInterrupt: If the miner is stopped by a manual interruption.
            Exception: For unforeseen errors during the miner's operation, which are logged for diagnosis.
        """

        # Registration was checked during BaseNeuron initialization. Confirm it
        # without forcing another full metagraph sync before useful work starts.
        self.check_registered()

        bt.logging.info(f"Validator starting at block: {self.block}")

        # This loop maintains the validator's operations until intentionally stopped.
        try:
            while not self.should_exit:
                bt.logging.info(f"step({self.step}) block({self.block})")
                try:
                    # Run multiple forwards concurrently.
                    self.loop.run_until_complete(self.concurrent_forward())

                    if self.should_exit:
                        break

                    # Sync metagraph and potentially set weights.
                    self.sync()
                    self.step += 1
                except Exception as err:
                    # A transient backend, miner, dashboard, or RPC failure must
                    # fail one round, not silently terminate the validator.
                    bt.logging.error(f"Validation round failed: {err}")
                    bt.logging.debug(
                        str(print_exception(type(err), err, err.__traceback__))
                    )
                    time.sleep(5)

        # If someone intentionally stops the validator, it'll safely terminate operations.
        except KeyboardInterrupt:
            axon = getattr(self, "axon", None)
            if axon is not None:
                axon.stop()
            bt.logging.success("Validator killed by keyboard interrupt.")
            exit()

        # Initialization/loop failures outside an individual round are fatal.
        except Exception as err:
            bt.logging.error(f"Error during validation: {str(err)}")
            bt.logging.debug(str(print_exception(type(err), err, err.__traceback__)))

    def run_in_background_thread(self):
        """
        Starts the validator's operations in a background thread upon entering the context.
        This method facilitates the use of the validator in a 'with' statement.
        """
        if not self.is_running:
            bt.logging.debug("Starting validator in background thread.")
            self.should_exit = False
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.is_running = True
            bt.logging.debug("Started")

    def stop_run_thread(self):
        """
        Stops the validator's operations that are running in the background thread.
        """
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def __enter__(self):
        self.run_in_background_thread()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Stops the validator's background operations upon exiting the context.
        This method facilitates the use of the validator in a 'with' statement.

        Args:
            exc_type: The type of the exception that caused the context to be exited.
                      None if the context was exited without an exception.
            exc_value: The instance of the exception that caused the context to be exited.
                       None if the context was exited without an exception.
            traceback: A traceback object encoding the stack trace.
                       None if the context was exited without an exception.
        """
        if self.is_running:
            bt.logging.debug("Stopping validator in background thread.")
            self.should_exit = True
            self.thread.join(5)
            self.is_running = False
            bt.logging.debug("Stopped")

    def prepare_weights(self):
        """Build the exact SDK-constrained vector that would be submitted."""
        local_scores = np.nan_to_num(
            np.asarray(self.scores, dtype=np.float32),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        local_scores = np.clip(local_scores, 0.0, None)
        max_winners = max(1, int(os.getenv("POKER44_WEIGHT_WINNERS", "10")))
        local_scores = retain_top_scores(local_scores, max_winners=max_winners)
        total = float(local_scores.sum())
        if total <= 0.0:
            return None
        raw_weights = local_scores / total
        processed_uids, processed_weights = process_weights_for_netuid(
            uids=self.metagraph.uids,
            weights=raw_weights,
            netuid=self.config.netuid,
            subtensor=self.subtensor,
            metagraph=self.metagraph,
        )
        uint_uids, uint_weights = convert_weights_and_uids_for_emit(
            uids=processed_uids,
            weights=processed_weights,
        )
        return processed_uids, processed_weights, uint_uids, uint_weights

    def set_weights(self, prepared_weights=None):
        """
        Sets the validator weights to the metagraph hotkeys based on the scores it has received from the miners. The weights determine the trust and incentive level the validator assigns to miner nodes on the network.
        """

        # Check if self.scores contains any NaN values and log a warning if it does.
        if np.isnan(self.scores).any():
            bt.logging.warning(
                "Scores contain NaN values. This may be due to a lack of responses from miners, or a bug in your reward functions."
            )

        # Validators are the sole authority for their weight vector. No backend
        # endpoint is consulted here.
        prepared = prepared_weights or self.prepare_weights()
        if prepared is None:
            bt.logging.warning(
                "Skipping weight submission: no positive evaluated scores"
            )
            return False
        processed_weight_uids, processed_weights, uint_uids, uint_weights = prepared
        bt.logging.info(
            "Using validator-local reward scores for weights | "
            f"nonzero={int(np.count_nonzero(processed_weights))}"
        )
        bt.logging.debug("processed_weights", processed_weights)
        bt.logging.debug("processed_weight_uids", processed_weight_uids)
        bt.logging.debug("uint_weights", uint_weights)
        bt.logging.debug("uint_uids", uint_uids)

        wait_for_inclusion = bool(self.config.neuron.wait_for_inclusion)
        wait_for_finalization = bool(self.config.neuron.wait_for_finalization)

        # Set the weights on chain via our subtensor connection.
        response = self.subtensor.set_weights(
            wallet=self.wallet,
            netuid=self.config.netuid,
            uids=uint_uids,
            weights=uint_weights,
            wait_for_finalization=wait_for_finalization,
            wait_for_inclusion=wait_for_inclusion,
            version_key=self.spec_version,
        )
        if isinstance(response, tuple):
            result, msg = response
        else:
            # ExtrinsicResponse itself is truthy even when success=False.
            result = bool(getattr(response, "success", False))
            msg = getattr(response, "message", str(response))
        if (
            result is False
            and "get_encrypted_commit() missing 1 required positional argument: 'hotkey'"
            in str(msg)
        ):
            bt.logging.warning(
                "Detected bittensor commit-reveal hotkey bug; retrying with local fallback."
            )
            try:
                result, msg = self._set_weights_commit_reveal_fallback(
                    uint_uids=uint_uids,
                    uint_weights=uint_weights,
                    wait_for_inclusion=wait_for_inclusion,
                    wait_for_finalization=wait_for_finalization,
                )
            except Exception as err:
                result, msg = False, str(err)
        if (
            result is False
            and "Call function 'SubtensorModule.commit_crv3_weights' not found"
            in str(msg)
        ):
            bt.logging.warning(
                "commit_crv3_weights is unavailable on the current RPC; falling back to classic set_weights."
            )
            result, msg = self._set_weights_classic_fallback(
                uint_uids=uint_uids,
                uint_weights=uint_weights,
                wait_for_inclusion=wait_for_inclusion,
                wait_for_finalization=wait_for_finalization,
            )
        if result is True and (wait_for_inclusion or wait_for_finalization):
            bt.logging.info(f"set_weights confirmed on chain: {msg}")
        elif result is True:
            bt.logging.info(
                f"set_weights submitted to chain without confirmation: {msg}"
            )
        else:
            bt.logging.error(f"set_weights failed: {msg}")
        write_snapshot = getattr(self, "_write_runtime_snapshot", None)
        if callable(write_snapshot):
            nonzero_uids = len([weight for weight in uint_weights if int(weight) > 0])
            write_snapshot(
                status="running",
                extra={
                    "last_set_weights_success": bool(result),
                    "last_set_weights_message": str(msg),
                    "last_set_weights_wait_for_inclusion": wait_for_inclusion,
                    "last_set_weights_wait_for_finalization": wait_for_finalization,
                    "last_set_weights_nonzero_uids": nonzero_uids,
                    "last_set_weights_source": "validator_local_reward",
                },
            )
        return bool(result)

    def _set_weights_commit_reveal_fallback(
        self,
        uint_uids: List[int],
        uint_weights: List[int],
        wait_for_inclusion: bool,
        wait_for_finalization: bool,
    ):
        """Fallback for bittensor 9.6.0 commit-reveal path, which omits `hotkey`."""
        from bittensor.core.extrinsics.commit_reveal import (
            _do_commit_reveal_v3,
            convert_and_normalize_weights_and_uids,
            get_encrypted_commit,
        )

        current_block = self.subtensor.get_current_block()
        subnet_hyperparameters = self.subtensor.get_subnet_hyperparameters(
            self.config.netuid, block=current_block
        )
        normalized_uids, normalized_weights = convert_and_normalize_weights_and_uids(
            uint_uids, uint_weights
        )
        commit_for_reveal, reveal_round = get_encrypted_commit(
            uids=normalized_uids,
            weights=normalized_weights,
            version_key=self.spec_version,
            tempo=subnet_hyperparameters.tempo,
            current_block=current_block,
            netuid=self.config.netuid,
            subnet_reveal_period_epochs=subnet_hyperparameters.commit_reveal_period,
            block_time=12.0,
            hotkey=self.wallet.hotkey.public_key,
        )
        return _do_commit_reveal_v3(
            subtensor=self.subtensor,
            wallet=self.wallet,
            netuid=self.config.netuid,
            commit=commit_for_reveal,
            reveal_round=reveal_round,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
            period=8,
        )

    def _set_weights_classic_fallback(
        self,
        uint_uids: List[int],
        uint_weights: List[int],
        wait_for_inclusion: bool,
        wait_for_finalization: bool,
    ):
        """Fallback to classic set_weights when commit-reveal v3 is unavailable."""
        from bittensor.core.extrinsics.set_weights import set_weights_extrinsic

        return set_weights_extrinsic(
            subtensor=self.subtensor,
            wallet=self.wallet,
            netuid=self.config.netuid,
            uids=uint_uids,
            weights=uint_weights,
            version_key=self.spec_version,
            wait_for_inclusion=wait_for_inclusion,
            wait_for_finalization=wait_for_finalization,
            period=8,
        )

    def resync_metagraph(self):
        """Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph."""
        bt.logging.info("resync_metagraph()")

        # Copies state of metagraph before syncing.
        previous_metagraph = copy.deepcopy(self.metagraph)

        # Sync the metagraph.
        self.metagraph.sync(subtensor=self.subtensor)

        # Check if the metagraph axon info has changed.
        if previous_metagraph.axons == self.metagraph.axons:
            return

        bt.logging.info(
            "Metagraph updated, re-syncing hotkeys, dendrite pool and moving averages"
        )
        # Zero out all hotkeys that have been replaced.
        for uid, hotkey in enumerate(self.hotkeys):
            if hotkey != self.metagraph.hotkeys[uid]:
                self.scores[uid] = 0  # hotkey has been replaced

        # Check to see if the metagraph has changed size.
        # If so, we need to add new hotkeys and moving averages.
        if len(self.hotkeys) < len(self.metagraph.hotkeys):
            # Update the size of the moving average scores.
            new_moving_average = np.zeros((self.metagraph.n))
            min_len = min(len(self.hotkeys), len(self.scores))
            new_moving_average[:min_len] = self.scores[:min_len]
            self.scores = new_moving_average

        # Update the hotkeys.
        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

    def update_scores(self, rewards: np.ndarray, uids: List[int]):
        """Performs exponential moving average on the scores based on the rewards received from the miners."""

        # Check if rewards contains NaN values.
        if np.isnan(rewards).any():
            bt.logging.warning(f"NaN values detected in rewards: {rewards}")
            # Replace any NaN values in rewards with 0.
            rewards = np.nan_to_num(rewards, nan=0)

        # Ensure rewards is a numpy array.
        rewards = np.asarray(rewards)

        # Check if `uids` is already a numpy array and copy it to avoid the warning.
        if isinstance(uids, np.ndarray):
            uids_array = uids.copy()
        else:
            uids_array = np.array(uids)

        # Handle edge case: If either rewards or uids_array is empty.
        if rewards.size == 0 or uids_array.size == 0:
            bt.logging.info(f"rewards: {rewards}, uids_array: {uids_array}")
            bt.logging.warning(
                "Either rewards or uids_array is empty. No updates will be performed."
            )
            return

        # Check if sizes of rewards and uids_array match.
        if rewards.size != uids_array.size:
            raise ValueError(
                f"Shape mismatch: rewards array of shape {rewards.shape} "
                f"cannot be broadcast to uids array of shape {uids_array.shape}"
            )

        # Compute forward pass rewards, assumes uids are mutually exclusive.
        # shape: [ metagraph.n ]
        scattered_rewards: np.ndarray = np.zeros_like(self.scores)
        scattered_rewards[uids_array] = rewards
        bt.logging.debug(f"Scattered rewards: {rewards}")

        # Update scores with rewards produced by this step.
        # shape: [ metagraph.n ]
        alpha: float = self.config.neuron.moving_average_alpha
        self.scores: np.ndarray = alpha * scattered_rewards + (1 - alpha) * self.scores
        bt.logging.debug(f"Updated moving avg scores: {self.scores}")

    def should_set_weights(self) -> bool:
        return (
            bool(np.any(np.asarray(self.scores) > 0.0)) and super().should_set_weights()
        )

    def save_state(self):
        """Saves the state of the validator to a file."""
        bt.logging.info("Saving validator state.")

        # Save the state of the validator to file.
        state_path = self.config.neuron.full_path + "/state.npz"
        temporary_path = state_path + ".tmp.npz"
        np.savez(
            temporary_path,
            step=self.step,
            scores=self.scores,
            hotkeys=self.hotkeys,
        )
        os.replace(temporary_path, state_path)
        write_snapshot = getattr(self, "_write_runtime_snapshot", None)
        if callable(write_snapshot):
            write_snapshot(
                status="running",
                extra={
                    "step": int(self.step),
                    "score_slots": int(len(self.scores)),
                    "nonzero_scores": int(np.count_nonzero(self.scores)),
                },
            )

    def load_state(self):
        """Restore scores by hotkey, tolerating first start and corrupt checkpoints."""
        state_path = self.config.neuron.full_path + "/state.npz"
        if not os.path.exists(state_path):
            bt.logging.info("No validator checkpoint found; starting with zero scores")
            self.save_state()
            return
        try:
            with np.load(state_path, allow_pickle=False) as state:
                previous_hotkeys = [str(value) for value in state["hotkeys"].tolist()]
                previous_scores = np.asarray(state["scores"], dtype=np.float32)
                self.step = int(state["step"])
            score_by_hotkey = {
                hotkey: float(previous_scores[index])
                for index, hotkey in enumerate(previous_hotkeys)
                if index < len(previous_scores)
            }
            self.scores = np.asarray(
                [score_by_hotkey.get(str(hotkey), 0.0) for hotkey in self.hotkeys],
                dtype=np.float32,
            )
            bt.logging.info(
                f"Validator checkpoint restored | step={self.step} scores={len(self.scores)}"
            )
        except Exception as exc:
            bt.logging.error(
                f"Validator checkpoint is unreadable; starting clean: {exc}"
            )
            self.step = 0
            self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
            self.save_state()
