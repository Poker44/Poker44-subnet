"""Poker44 miner entrypoint.

Every miner owns and loads its detection model in this process. The axon invokes
that resident model directly for every ``SessionDetectionSynapse`` request.
"""

import time
from typing import Tuple

import bittensor as bt

from poker44.base.miner import BaseMinerNeuron
from poker44.miner.config import MinerModelConfig
from poker44.miner.loader import load_model
from poker44.miner.service import MinerInferenceService
from poker44.protocol import SessionDetectionSynapse


class Miner(BaseMinerNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        self.model_config = MinerModelConfig.from_env()
        self.model = load_model(self.model_config)
        self.inference = MinerInferenceService(self.model, self.model_config)
        bt.logging.info(
            "Poker44 miner model loaded | "
            f"factory={self.model_config.factory} "
            f"version={self.model.version} device={self.model_config.device}"
        )

    async def forward(
        self, synapse: SessionDetectionSynapse
    ) -> SessionDetectionSynapse:
        if synapse.protocol_version != "1":
            raise ValueError(
                f"Unsupported Poker44 protocol version: {synapse.protocol_version}"
            )
        if not synapse.window_id.strip():
            raise ValueError("window_id is required")
        scores = await self.inference.predict(synapse.sessions)
        synapse.risk_scores = scores
        synapse.predictions = [score >= 0.5 for score in scores]
        synapse.model_version = self.model.version
        bt.logging.info(
            f"Scored {len(scores)} subject sessions for window={synapse.window_id}"
        )
        return synapse

    async def blacklist(self, synapse: SessionDetectionSynapse) -> Tuple[bool, str]:
        return self.common_blacklist(synapse)

    async def priority(self, synapse: SessionDetectionSynapse) -> float:
        return self.caller_priority(synapse)


if __name__ == "__main__":
    with Miner() as miner:
        bt.logging.info("Poker44 miner axon is running")
        while True:
            bt.logging.info(
                f"Miner UID: {miner.uid} | Incentive: {miner.metagraph.I[miner.uid]}"
            )
            time.sleep(5 * 60)
