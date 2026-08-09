# Poker44 v3.1.0 miner training benchmark

Poker44 v3.1.0 publishes a labelled schema-v4.1 development corpus generated
only by public miner-training tournaments. This corpus is separate from live
evaluation: training tournament data is never eligible for a validator
evaluation window, and private evaluation labels remain inside validators.

## Tournament source

The platform schedules three free miner-training tournaments per day, eight
hours apart. Each tournament reserves ten places:

- five browser-driven Poker44 agents;
- three to five signed-in human players;
- no coldkey verification;
- no invitation code;
- no entry fee.

A tournament starts with all five agents and at least three present humans.
Registration is limited to five humans, so agent seats cannot be consumed by
public registrations. Participants consent to the same in-platform collection
used to construct the development corpus.

## API

The staging API base is:

```text
https://staging.platform.poker44.net/api/v1/benchmark
```

The endpoints are public and require no account or Bittensor authentication:

```text
GET /api/v1/benchmark
GET /api/v1/benchmark/releases
GET /api/v1/benchmark/latest
GET /api/v1/benchmark/latest/download
GET /api/v1/benchmark/releases/:releaseId
GET /api/v1/benchmark/releases/:releaseId/download
```

`GET /api/v1/benchmark` returns schedule and latest-release metadata. The
backend retains the latest immutable release until a later completed training
tournament passes publication checks.

```bash
curl -sS https://staging.platform.poker44.net/api/v1/benchmark
curl -sS -o poker44-training.json \
  https://staging.platform.poker44.net/api/v1/benchmark/latest/download
```

Every release has a stable `releaseId`, a benchmark-specific `releaseVersion`,
SHA-256 `datasetHash`, publication time, class counts, item count and decision
count.
The Poker44 product and benchmark contract described here is version `3.1.0`;
`releaseVersion` identifies each generated corpus release and is not the product
version.
Historical release URLs are immutable and may be cached by `datasetHash`. The
SHA-256 hash is calculated over the exact bytes returned by `/download`.

## Dataset contract

The download response contains `dataset.items`. Each item has the exact
schema-v4.1 payload accepted by the miner model plus a separate training label:

```json
{
  "itemId": "stable-public-item-id",
  "payload": {
    "schema_version": "4.1",
    "item_id": "stable-public-item-id",
    "window_id": "training_public_source",
    "decisions": [
      {
        "decision_number": 1,
        "phase": "preflop",
        "position_group": "late",
        "pressure": "facing_bet",
        "action_type": "call",
        "size_bucket": "not_applicable",
        "is_all_in": false
      },
      {
        "decision_number": 2,
        "phase": "flop",
        "position_group": "late",
        "pressure": "no_call",
        "action_type": "bet",
        "size_bucket": "half_pot",
        "is_all_in": false
      },
      {
        "decision_number": 3,
        "phase": "turn",
        "position_group": "early",
        "pressure": "facing_bet",
        "action_type": "fold",
        "size_bucket": "not_applicable",
        "is_all_in": false
      },
      {
        "decision_number": 4,
        "phase": "river",
        "position_group": "blinds",
        "pressure": "no_call",
        "action_type": "check",
        "size_bucket": "not_applicable",
        "is_all_in": false
      }
    ]
  },
  "label": 0,
  "labelName": "human"
}
```

Real items contain exactly four decisions and at least one postflop decision.
`label` is `0` for human and `1` for bot. Feed only each `payload` to the model;
the label is the supervised target.

The public corpus excludes raw telemetry, cards, exact chip amounts, timing,
user IDs, actor groups, bot-family identifiers, tournament IDs and capture
provenance. These exclusions prevent identity/provenance shortcuts and keep the
training input aligned with `MicroSessionDetectionSynapse`.

## Publication controls

After a tournament completes, the backend finishes session assembly and
publishes once only if the corpus:

- contains both classes;
- covers at least three human actors and five agent families;
- preserves the four-decision v4.1 contract;
- has no duplicate source decision;
- passes position and pressure distribution checks.

The complete dataset is stored in PostgreSQL before it becomes public. A
release is never mutated or rebuilt in place; a later valid tournament creates
a new release and becomes `latest`.

## Recommended use

1. Fetch `/benchmark` and record the latest `datasetHash`.
2. Download its stable `downloadUrl` or `/benchmark/latest`.
3. Verify the hash of the canonical dataset JSON in your ingestion pipeline.
4. Train on `payload` and use `label` only as the target.
5. Split by release when several tournaments are available.
6. Do not use item IDs, window IDs, release order or hashes as model features.

This is training data, not the live evaluation window. Validators continue to
send label-free items privately through `MicroSessionDetectionSynapse`.
