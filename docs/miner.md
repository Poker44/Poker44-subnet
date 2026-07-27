# Miner

The miner exposes `SessionDetectionSynapse` on its axon and keeps its classifier loaded in memory. It does not download a validator-selected artifact and does not expose a second inference server.

Input is an ordered list of subject sessions with hands and telemetry. New
tournament data uses
[`subject-session.v2`](../contracts/subject-session.v2.schema.json): absolute
timestamps and platform identifiers are removed, action times become relative,
and telemetry exposes allowlisted event types, target categories and bucketed
values. Labels such as `is_bot`, `label`, `ground_truth` and `bot_family` are
forbidden at the inference boundary.

Output is one calibrated bot probability per input session, in input order.
Miners must not produce one score per hand. Session and window identifiers,
request order and request timing are metadata rather than behavioral features.

Configure a production model with `POKER44_MODEL_FACTORY=module:create_model`.
Optional limits are `POKER44_MAX_SESSIONS_PER_REQUEST`,
`POKER44_MAX_REQUEST_BYTES` and normal Bittensor axon/blacklist settings. The
factory is imported during startup so configuration errors fail fast.

The validator checks response shape, finite values and range. Invalid or missing
responses receive zero reward for that evaluation cycle.

## Encrypted Axon endpoint

Miners may opt in to encrypted endpoint commitments. The real Axon endpoint is
published as hotkey-bound ciphertext and is replaced in the public metagraph by
`192.0.2.1:1234` only after a finalized read-back confirms the commitment.
Updated validators resolve the real endpoint locally.

```bash
export POKER44_ENCRYPTED_AXON_ENABLED=true
export POKER44_AXON_EXTERNAL_IP=<public_ipv4>
export POKER44_AXON_EXTERNAL_PORT=<axon_port>
```

The netuid 126 public key is bundled with the release. A miner moving from a
previously exposed address should change origin IP before enabling protection.
See [encrypted Axon endpoints](encrypted-axon-endpoints.md) for the security
model and rollout requirements.

There are no longer participant-facing competition rounds. Miners remain
reachable and receive requests only after recurring tournaments have generated
enough quality-checked data for a sealed window. Timing is data-dependent and
is not guaranteed to be daily.

See the
[tournament evaluation workflow](tournament-evaluation-workflow.md) for the
exact payload, privacy boundary, transition table, defensive parser example and
model adaptation checklist.
