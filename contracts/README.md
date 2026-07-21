# Poker44 v2 contracts

This directory is the language-neutral boundary between the Poker44 services.
Contracts are versioned explicitly and must remain backward compatible within a
major version.

- `subject-session.v1.schema.json`: miner-visible poker session. It never contains
  the human/bot ground-truth label.
- `validation-report.v2.schema.json`: signed validator observability report sent
  to the dashboard. It never controls validator rewards or weights.

Validation reports use `schema_version: "2"`. Producers and consumers reject
other report versions so contract drift fails explicitly.

TAO deposits do not use a public payment-intent contract. The platform credits
only finalized transfers whose sender is already linked and verified for the
authenticated user.

Ground truth is transported only in the validator lease envelope served by the
platform `subnetData` module. It is separated from the miner payload before the Bittensor
synapse is created.
