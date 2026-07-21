"""Testnet Axon entrypoint for hotkeys whose endpoints are already on-chain."""

import os
import signal
import threading
from typing import Tuple

import bittensor as bt

from poker44.miner.config import MinerModelConfig
from poker44.miner.loader import load_model
from poker44.miner.service import MinerInferenceService
from poker44.protocol import SessionDetectionSynapse


class TestnetMiner:
    """Serve a model without coupling availability to public-RPC bootstrap."""

    def __init__(self) -> None:
        port = int(os.environ["POKER44_AXON_PORT"])
        self.allowed_validator = os.environ["POKER44_VALIDATOR_HOTKEY"]
        self.wallet = bt.Wallet(
            name=os.environ.get("POKER44_WALLET_NAME", "poker44-testnet"),
            hotkey=os.environ["POKER44_WALLET_HOTKEY"],
            path=os.environ.get("POKER44_WALLET_PATH", "/wallets"),
        )
        self.model_config = MinerModelConfig.from_env()
        self.model = load_model(self.model_config)
        self.inference = MinerInferenceService(self.model, self.model_config)
        self.axon = bt.Axon(
            wallet=self.wallet,
            ip="0.0.0.0",
            port=port,
            external_ip=os.environ["POKER44_AXON_EXTERNAL_IP"],
            external_port=port,
        )
        self.axon.attach(
            forward_fn=self.forward,
            blacklist_fn=self.blacklist,
            priority_fn=self.priority,
        )
        self.stop_event = threading.Event()

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
        caller = getattr(synapse.dendrite, "hotkey", None)
        if caller != self.allowed_validator:
            return True, "Hotkey not in validator allowlist"
        return False, "Whitelisted validator hotkey"

    async def priority(self, synapse: SessionDetectionSynapse) -> float:
        return 1.0

    def run(self) -> None:
        bt.logging.info(
            "Starting pre-registered testnet Axon | "
            f"hotkey={self.wallet.hotkey.ss58_address} "
            f"model={self.model.version} port={self.axon.port}"
        )
        if os.environ.get("POKER44_SERVE_AXON_ON_CHAIN", "false").lower() == "true":
            subtensor = bt.Subtensor(
                network=os.environ.get(
                    "POKER44_SUBTENSOR_ENDPOINT",
                    "wss://test.finney.opentensor.ai:443",
                )
            )
            response = subtensor.serve_axon(
                netuid=int(os.environ.get("POKER44_NETUID", "492")),
                axon=self.axon,
            )
            if getattr(response, "success", bool(response)) is False:
                raise RuntimeError(
                    f"Could not publish testnet Axon: {getattr(response, 'message', response)}"
                )
            bt.logging.info("Testnet Axon endpoint published on chain")
        self.axon.start()
        self.stop_event.wait()
        self.axon.stop()


if __name__ == "__main__":
    bt.logging.set_info()
    miner = TestnetMiner()

    def stop(*_args) -> None:
        miner.stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    miner.run()
