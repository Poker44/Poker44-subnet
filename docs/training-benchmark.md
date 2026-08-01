# Poker44 training data and benchmark status

This page documents the training-data status for Poker44 subnet `126` and the
schema-v4.1 miner contract deployed with subnet release `0.2.1`.

## Current status

The legacy public hand-chunk benchmark was retired on 31 July 2026. The former
routes below are no longer part of the public API and return
`ROUTE_NOT_FOUND`:

```text
GET /api/v1/benchmark
GET /api/v1/benchmark/releases
GET /api/v1/benchmark/chunks
GET /api/v1/benchmark/chunks/:chunkId
```

Do not build a v3.0 miner around old release files, hand chunks,
`groundTruth`, `groundTruthLabels` or the v1/v2 session schemas. They do not
represent the current evaluation input.

At launch there is no public labeled v4.1 training corpus. Poker44 plans to
publish a labeled development corpus after telemetry collection and dataset
quality are stable. No publication date, endpoint or release format should be
assumed until it is announced and documented here.

Publishing a development corpus will not expose evaluation ground truth.
Labels for live evaluation windows remain private to validators.

## What miners receive during evaluation

Miners do not download the live evaluation dataset through HTTP. An authorized
validator sends one `MicroSessionDetectionSynapse` request over Bittensor with:

- `contract_version: "microsession-v1"`;
- the window ID, SHA-256 dataset hash and validator-bound query ID;
- an ordered `items` array of schema-v4.1 micro-sessions.

Each item contains exactly four coarse strategic decisions and at least one
postflop decision. The only decision fields are:

- `decision_number`
- `phase`
- `position_group`
- `pressure`
- `action_type`
- `size_bucket`
- `is_all_in`

The request contains no label, actor identity, bot family, cards, hand object,
exact chip amount, timestamp, raw interaction telemetry, tournament identity
or capture provenance. The normative schema is
[`contracts/subject-session.v4.1.schema.json`](../contracts/subject-session.v4.1.schema.json),
with a complete request in
[`contracts/examples/microsession-request.v1.json`](../contracts/examples/microsession-request.v1.json).

## Required miner output

Return one finite probability in `[0, 1]` for every item, preserving input
order:

```json
{
  "risk_scores": [0.12, 0.84, 0.51]
}
```

`0` is strongest human confidence and `1` is strongest bot confidence. The
validator scores the continuous probabilities, so returning only hard class
labels is insufficient. Invalid, missing, non-finite, out-of-range or
wrong-length responses score zero.

The complete response example is
[`contracts/examples/microsession-response.v1.json`](../contracts/examples/microsession-response.v1.json).

## Scoring

Validators keep labels and private actor groups locally. Actor-balanced sample
weights give equal mass to each actor within each class. Miner quality is:

```text
0.50 * average-precision skill
+ 0.30 * recall at <=5% false-positive rate
+ 0.20 * Brier skill
```

The highest positive finite score wins the competitive miner share. Exact ties
use the lower UID.

## Development guidance before a corpus release

Miners can implement and validate the transport, strict schema handling,
inference shape and calibrated output locally. Synthetic fixtures may be used
for software tests, but they are not representative performance benchmarks.

Recommended checks:

1. Accept only `contract_version: "microsession-v1"` and schema `4.1`.
2. Validate exactly four decisions with at least one postflop decision.
3. Preserve item order and return exactly one score per item.
4. Reject or safely fail malformed inputs and never emit non-finite values.
5. Do not use IDs, hashes, order or request timing as behavioral features.
6. Test probability calibration as well as ranking performance.

The current implementation target is the `main` branch at release `0.2.1`.
The old `dev@9cd1df5` hand/telemetry contract is obsolete.
