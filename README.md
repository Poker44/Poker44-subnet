# Poker44 subnet

Poker44 is a decentralized evaluation network for online-poker bot detection.
It rewards models that can assign a calibrated bot-risk probability to short
sequences of poker decisions produced by humans and external agents playing in
the same tournament environment.

The objective is practical: help poker platforms identify automated play from
behavioral evidence while evaluating every competing model against the same
private ground truth.

## The problem

Poker bots and human players act inside the same game rules, so reliable
detection cannot depend on a single action or a known bot signature. A useful
system must generalize across players and bot families, resist identity and
provenance shortcuts, and produce calibrated probabilities rather than only
hard human/bot labels.

Static public evaluation labels also make a benchmark easier to overfit. In
Poker44, live evaluation labels and private actor groups remain inside each
validator and never reach miners.

## How Poker44 evaluates models

1. Humans and external browser agents play on the Poker44 tournament platform.
2. The platform captures consented gameplay and interaction telemetry as
   private source data, then applies quality and eligibility controls.
3. It derives a balanced, immutable schema-v4.1 window of four-decision
   micro-sessions. Raw telemetry, hands, cards, timing, exact amounts, labels
   and source identities are excluded from the miner-visible payload.
4. Every validator leases the same ordered items, verifies the same
   `dataset_hash` and keeps labels and actor groups locally.
5. Validators query every eligible reachable miner through
   `MicroSessionDetectionSynapse`.
6. Each miner returns one continuous `risk_score` in `[0, 1]` per item. The
   validator scores the response locally and selects one deterministic winner.

```text
tournament play
      |
      v
private hands + telemetry
      |
      v
quality gates and v4.1 micro-session construction
      |
      v
same immutable window for every validator
      |
      v
miner risk scores -> private scoring -> deterministic winner
```

## The miner's role

A miner operates an online Bittensor Axon and serves a detection model. Its
responsibility is deliberately narrow:

- accept `contract_version: "microsession-v1"` requests;
- process the ordered schema-v4.1 `items` list;
- return exactly one finite, calibrated `risk_score` per item;
- remain registered, authenticated and reachable when a window is evaluated.

Miners do not download the live evaluation dataset or receive its labels.
Separately, they may play free public miner-training tournaments and download
the resulting labelled v4.1 corpus for model development. The model repository
and model artifact are not inspected in the current release. There is no
coldkey-level hotkey limit or legacy evaluation fallback.

Start with the [miner integration guide](docs/miner.md) and the canonical
[request](contracts/examples/microsession-request.v1.json) and
[response](contracts/examples/microsession-response.v1.json) examples.

## Scoring and current emission policy

Validator scoring is actor-balanced so one prolific player cannot dominate a
window:

```text
0.50 * average-precision skill
+ 0.30 * recall at <=5% false-positive rate
+ 0.20 * Brier skill
```

Invalid, missing, non-finite, out-of-range or wrong-length responses score
zero. The highest positive finite score wins; exact ties use the lower UID.

During the current transition, the validator target assigns 30% to the live
subnet owner, 5% to the tournament-funding hotkey and 65% to the winning miner.
Winner-takes-all applies to that competitive miner share. The unchanged target
is refreshed every 720 blocks without querying miners again. There is no EMA.

## Current compatibility target

- Product evaluation: Poker44 v3.0
- Subnet release: `0.2.8`
- Branch: `dev`
- Miner-visible schema: `4.1`
- Bittensor transport: `MicroSessionDetectionSynapse`
- Contract version: `microsession-v1`
- Default network: Finney, netuid `126`

The pre-release `dev@9cd1df5` contract and retired hand-chunk benchmark are not
compatible with the deployed evaluation path.

## Documentation

| Document | Purpose |
| --- | --- |
| [Miner guide](docs/miner.md) | Request contract, model interface, authentication and deployment |
| [Tournament evaluation workflow](docs/tournament-evaluation-workflow.md) | Complete data-to-reward lifecycle and privacy boundary |
| [Miner training benchmark](docs/training-benchmark.md) | Public tournament cadence, download API, labels and dataset contract |
| [Validator guide](docs/validator.md) | Window verification, miner selection, scoring and settlement |
| [Data contracts](contracts/README.md) | Normative v4.1 and validator-report schemas |
| [Encrypted Axon endpoints](docs/encrypted-axon-endpoints.md) | Optional endpoint protection and validator resolution |
| [Changelog](CHANGELOG.md) | Release and migration history |

## Repository checks

```bash
ruff check poker44 neurons tests
PYTHONPATH=. pytest -q
```

Poker44 is licensed under the [MIT License](LICENSE).
