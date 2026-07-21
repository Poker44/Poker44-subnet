# Miner

The miner exposes `SessionDetectionSynapse` on its axon and keeps its classifier loaded in memory. It does not download a validator-selected artifact and does not expose a second inference server.

Input is an ordered list of subject sessions with hands and telemetry. Labels such as `is_bot`, `label`, `ground_truth` and `bot_family` are forbidden at the inference boundary. Output is one calibrated bot probability per input session.

Configure a production model with `POKER44_MODEL_FACTORY=module:create_model`. Optional limits are `POKER44_MAX_SESSIONS_PER_REQUEST` and normal Bittensor axon/blacklist settings. The factory is imported during startup so configuration errors fail fast.

The validator checks response shape, finite values and range. Invalid or missing responses receive zero reward for that round.
