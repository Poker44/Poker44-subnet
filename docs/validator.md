# Validator

The validator owns the complete scoring decision:

1. Poll for a sealed evaluation window.
2. Acquire an idempotent validator-specific lease of the complete labelled snapshot.
3. Strip labels and send the same feature payload to reachable miner axons.
4. Compute reward locally from average precision, bot recall at low false-positive rate and Brier skill.
5. Update local EMA scores and submit the normalized vector on chain when cadence permits.
6. Mark the lease complete and report signed lifecycle events to the dashboard.

The session service never returns a weight vector and the dashboard is observability-only. Labels are separated from miner payloads by `poker44/platform/models.py`.

Every validator receives the same persisted payload list, order and
`dataset_hash`. The validator recomputes the canonical hash before any miner is
queried. A completed lease is not replayed after restart; the snapshot remains
active for validators that have not evaluated it until an operator atomically
publishes a newer tournament snapshot.

Key variables:

- `POKER44_SUBNET_DATA_URL`
- `POKER44_VALIDATOR_SESSIONS_PER_ROUND`
- `POKER44_MINERS_PER_ROUND`
- `POKER44_POLL_INTERVAL_SECONDS`
- `POKER44_DASHBOARD_REPORT_URL`
- `POKER44_DASHBOARD_REPORT_TIMEOUT_SECONDS`
- `POKER44_ENDPOINT_AUTO_PROVISION`
- `POKER44_ENDPOINT_PROVISIONING_URL`
- `POKER44_ENDPOINT_CACHE_FILE`

Requests to the session service and dashboard are signed by the validator hotkey with a timestamp and one-use nonce. Dashboard failures do not alter rewards; failure to acquire or complete the evaluation lease does.

## Encrypted endpoint resolution

Validators resolve opted-in miners before applying the normal v3 identity,
repository and coldkey eligibility filters. Public and protected miners can be
evaluated in the same sealed window.

By default, a validator requests the shared endpoint key from the configured
provisioning service using a signed, nonce-protected hotkey request. The
response is encrypted to an ephemeral transport key, bound to the requesting
validator and checked against the release fingerprint before being cached with
owner-only permissions. An operator may instead configure exactly one of
`POKER44_ENDPOINT_PRIVATE_KEY` or `POKER44_ENDPOINT_PRIVATE_KEY_FILE`.

If provisioning or commitment refresh fails, public miners remain available
and the last valid protected endpoint set is retained. A masked Axon without a
decryptable commitment is skipped rather than queried at its placeholder
address. See [encrypted Axon endpoints](encrypted-axon-endpoints.md).

## Tournament-driven cadence

Competition rounds are removed. Recurring tournaments produce source data,
while an operator publishes a quality-audited strategic snapshot after the
tournament completes. The active snapshot does not expire on a wall-clock TTL.
If no snapshot is available, or this validator already completed its
idempotent lease, it does not query miners and continues polling.

Legacy names such as `ValidationRound`,
`POKER44_VALIDATOR_SESSIONS_PER_ROUND`,
`POKER44_MINERS_PER_ROUND` and `round_id` remain for compatibility. In this
codebase, they refer to one internal evaluation cycle identified by a sealed
`window_id`; they are not tournament stages and do not allow miners to join a
later competition round.

`POKER44_VALIDATOR_SESSIONS_PER_ROUND` remains in the wire request for
compatibility, but the backend returns the complete snapshot so different
validator settings cannot create different evaluation datasets.

The complete upstream tournament lifecycle and downstream miner contract are
documented in
[`docs/tournament-evaluation-workflow.md`](tournament-evaluation-workflow.md).
