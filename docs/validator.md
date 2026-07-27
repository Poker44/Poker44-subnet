# Validator

The validator owns the complete scoring decision:

1. Poll for a sealed evaluation window.
2. Acquire an idempotent validator-specific lease of Nv labelled sessions.
3. Strip labels and send the same feature payload to reachable miner axons.
4. Compute reward locally from average precision, bot recall at low false-positive rate and Brier skill.
5. Update local EMA scores and submit the normalized vector on chain when cadence permits.
6. Mark the lease complete and report signed lifecycle events to the dashboard.

The session service never returns a weight vector and the dashboard is observability-only. Labels are separated from miner payloads by `poker44/platform/models.py`.

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

Competition rounds are removed. Recurring tournaments produce completed hands
and telemetry continuously, while the platform seals a new evaluation window
only after enough comparable, quality-checked sessions exist. If no sealed
window is available, the validator does not query miners and continues polling.
The delay between evaluation cycles is therefore data-dependent and may span
one or several days.

Legacy names such as `ValidationRound`,
`POKER44_VALIDATOR_SESSIONS_PER_ROUND`,
`POKER44_MINERS_PER_ROUND` and `round_id` remain for compatibility. In this
codebase, they refer to one internal evaluation cycle identified by a sealed
`window_id`; they are not tournament stages and do not allow miners to join a
later competition round.

The default validator request is 20 sessions. This matches the standard
20-seat tournament window configured by the platform: 10 eligible human
sessions and 10 eligible bot sessions. The value remains configurable for
larger future tournament profiles.

The complete upstream tournament lifecycle and downstream miner contract are
documented in
[`docs/tournament-evaluation-workflow.md`](tournament-evaluation-workflow.md).
