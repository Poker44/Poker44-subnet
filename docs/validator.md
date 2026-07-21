# Validator

The validator owns the complete scoring decision:

1. Read the current sealed evaluation window.
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

Requests to the session service and dashboard are signed by the validator hotkey with a timestamp and one-use nonce. Dashboard failures do not alter rewards; failure to acquire or complete the evaluation lease does.
