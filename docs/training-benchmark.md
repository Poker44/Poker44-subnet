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

`GET /api/v1/benchmark` returns schedule and preferred-release metadata,
including `stableAvailable` and the release `qualityTier`. While no stable
corpus exists, the preferred release is the newest `preview`; after a stable
corpus exists, the preferred release remains the newest `stable`. All preview
and stable releases remain available through `/releases`.

```bash
curl -sS https://staging.platform.poker44.net/api/v1/benchmark
curl -sS -o poker44-training.json \
  https://staging.platform.poker44.net/api/v1/benchmark/latest/download
```

Every release has a stable `releaseId`, a benchmark-specific `releaseVersion`,
SHA-256 `datasetHash`, publication time, class counts, item count and decision
count. It also declares `qualityTier` as `preview` or `stable` and includes the
number of completed miner-training tournaments accumulated into the corpus.
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

## Publication controls and quality tiers

After each tournament completes, the backend finishes session assembly and
builds a cumulative corpus from all completed miner-training tournaments up to
that release. A non-empty schema-valid corpus can be published as `preview` so
miners can validate ingestion and begin model development without waiting for
the stable-quality threshold.

A release is marked `stable` only when the cumulative corpus:

- contains both classes;
- covers at least three human actors and five agent families;
- preserves the four-decision v4.1 contract;
- has no duplicate source decision;
- passes position and pressure distribution checks.

The audit result and any failed controls remain visible in release metadata.
Preview means the corpus is usable for integration and experimentation, not
that it has passed Poker44's stable benchmark quality controls. The controls
are not disabled or relaxed to create a preview.

The complete dataset is stored in PostgreSQL before it becomes public. A
release is never mutated or rebuilt in place. Every later completed tournament
creates a new cumulative release; older URLs and hashes remain unchanged.

## Recommended use

1. Fetch `/benchmark` and record the latest `datasetHash`.
2. Inspect `qualityTier` and the audit. Prefer `stable` for comparable model
   results; use `preview` for ingestion, experimentation and early training.
3. Download its `downloadUrl` or `/benchmark/latest`.
4. Verify the hash of the canonical dataset JSON in your ingestion pipeline.
5. Train on `payload` and use `label` only as the target.
6. Split carefully when several cumulative releases are available; releases
   overlap by design, so do not treat them as independent samples.
7. Do not use item IDs, window IDs, release order or hashes as model features.

This is training data, not the live evaluation window. Validators continue to
send label-free items privately through `MicroSessionDetectionSynapse`.
