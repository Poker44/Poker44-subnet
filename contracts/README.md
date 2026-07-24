# Poker44 v2 contracts

This directory is the language-neutral boundary between the Poker44 services.
Contracts are versioned explicitly and must remain backward compatible within a
major version.

- `subject-session.v1.schema.json`: legacy miner-visible poker session retained
  during migration.
- `subject-session.v2.schema.json`: current tournament-sourced miner payload
  with pseudonymous identifiers, relative timing and sanitized telemetry. It
  never contains the human/bot ground-truth label.
- `validation-report.v2.schema.json`: signed validator observability report sent
  to the dashboard. It never controls validator rewards or weights.

Tournament subject sessions and validation reports independently use
`schema_version: "2"`. The enclosing Bittensor synapse retains
`protocol_version: "1"`; transport and feature-contract versions must not be
confused.

TAO deposits do not use a public payment-intent contract. The platform credits
only finalized transfers whose sender is already linked and verified for the
authenticated user.

Ground truth is transported only in the validator lease envelope served by the
platform `subnetData` module. It is separated from the miner payload before the Bittensor
synapse is created.

See
[`docs/tournament-evaluation-workflow.md`](../docs/tournament-evaluation-workflow.md)
for the complete data lifecycle, an example payload and miner migration
guidance.
