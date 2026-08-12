# Changelog

## 0.2.9 - 2026-08-12

- Set the default owner burn to 0%, retain 5% tournament funding and increase
  the round-winner share to 95%.
- Migrate inherited 90%, 70% and 30% runner defaults during auto-update while
  preserving an explicit `.env` or custom operator override.
- Advance the validator deployment gate so healthy `main` auto-update watchers
  fetch and apply this reviewed release.

## 0.2.5 - 2026-08-06

- Reduce the default owner burn from 70% to 30%, retain 5% tournament funding
  and increase the round-winner share from 25% to 65%.
- Migrate inherited 90% and 70% runner defaults during auto-update while
  preserving an explicit `.env` override.
- Advance the validator deployment gate so healthy `main` auto-update watchers
  fetch and apply this reviewed release.

## 0.2.4 - 2026-08-04

- Reissue the validator deployment gate so supervised validators reapply the
  current `main` release and its 70% owner burn, 5% tournament funding and 25%
  round-winner defaults.
- Keep the protocol and miner-visible schema unchanged; this operational
  release does not claim adoption by validators without a healthy auto-update
  watcher or by operators with explicit runtime overrides.

## 0.2.3 - 2026-08-04

- Read all finalized timelocked-weight commit buckets so validators reconcile
  accepted commits without false missing-commit warnings or redundant retries.
- Change the default transition allocation from 90/5/5 to 70% owner burn, 5%
  tournament funding and 25% round winner.
- Migrate the former runner-inherited 90% burn default during auto-update while
  preserving explicit `.env` and custom process overrides.
- Align miner, validator-workflow and training-data documentation with the
  deployed schema-v4.1 contract.
- Add canonical `MicroSessionDetectionSynapse` request and response examples.
- Mark the legacy public hand-chunk benchmark and pre-release dev contract as
  retired.

## 0.2.1 - 2026-07-31

- Trigger validator deployment of the production micro-session, 90/5/5
  settlement, dashboard reporting and reveal-reconciliation fixes.
- Start a PM2-supervised validator auto-update watcher by default.
- Verify the applied version and Git commit, retry failed deployments, support
  both documented PM2 validator names and keep updater state private.

## 0.2.0 - 2026-07-18

### Breaking

- Validator protocol spec increased to 2.
- Removed the `cycle` validator flow and old subnet-backend configuration
  aliases. Only signed platform round leases are supported.
- Validator reports require schema v2; schema-v1 reports are rejected.

### Added

- Local miner evaluation, reward calculation and on-chain weight settlement.
- Exponential failed-round backoff and terminal in-process quarantine.
- Explicit, disabled-by-default single-class scoring for bot-only release E2E.

### Fixed

- Failed settlement no longer hot-loops against the same lease.
- Weight submission evidence distinguishes commit acceptance and finalization.
