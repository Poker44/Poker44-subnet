# Poker44 subnet

Poker44 evaluates whether a poker subject session was produced by a human or a
bot. Sessions are now sourced from recurring poker tournaments and contain
consecutive hands plus sanitized behavioral telemetry. Labels stay inside the
validator; miners receive only features and return one bot-risk score per
session.

> **Tournament migration:** participant-facing competition rounds are being
> removed. Evaluations become data-driven and run when tournaments have
> produced enough quality-checked sessions, not on a guaranteed daily round
> schedule. See the
> [tournament evaluation workflow](docs/tournament-evaluation-workflow.md) for
> the lifecycle, the miner-visible v2 payload and the model migration checklist.

## Runtime flow

1. Recurring tournaments record poker actions and consented browser telemetry.
2. The platform assembles quality-checked sessions and seals a balanced,
   immutable window only when enough comparable data exists.
3. Each validator leases Nv sessions from that window.
4. The validator sends the unlabelled sessions to miner axons through `SessionDetectionSynapse`.
5. Each miner runs its own resident model and returns `risk_scores` in `[0,1]`.
6. The validator calculates rewards locally with `poker44/validator/evaluation/reward.py`, updates its EMA and submits its own weight vector on chain.
7. Signed lifecycle events are sent best-effort to the read-only dashboard backend.

No backend provides weights. There are no repository, commit, manifest or model-artifact checks in the evaluation path.

## Layout

```text
neurons/                    miner and validator entrypoints
contracts/                  versioned subject-session and validation schemas
poker44/protocol.py         shared Bittensor synapse
poker44/base/               common neuron lifecycle
poker44/miner/              resident model interface, loader and inference service
poker44/platform/           sealed-window/lease API client
poker44/validator/
  round_start/              acquire a validator-specific session lease
  evaluation/               query axons and compute local reward
  settlement/               EMA and on-chain weights
  reporting/                signed dashboard events
tests/                      contract and reward tests
```

The organization follows a clean entrypoint/protocol/base/client/phase separation, while keeping Poker44's model resident directly behind the miner axon.

## Miner model

Set `POKER44_MODEL_FACTORY=your_package.module:create_model`. The factory is loaded once when the miner starts and must return an object with:

```python
def predict(self, sessions: list[dict]) -> list[float]: ...
```

The output length must equal the session count. Ground-truth fields are rejected
at the miner boundary. Tournament sessions use the
[`subject-session.v2`](contracts/subject-session.v2.schema.json) contract.
Without a factory, the bundled reference model is used for smoke testing only.

## Validator services

Required variables include `POKER44_SUBNET_DATA_URL` and
`POKER44_VALIDATOR_SESSIONS_PER_ROUND`. `POKER44_DASHBOARD_REPORT_URL` controls
optional signed observability delivery. `_PER_ROUND` is a legacy configuration
name for one validator evaluation cycle; it is not a tournament round. See
`docs/validator.md` and `docs/miner.md`.

Run tests with:

```bash
PYTHONPATH=. pytest -q
```
