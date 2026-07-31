# Miner

The Axon exposes only `MicroSessionDetectionSynapse` (`microsession-v1`). Its
`items` are exact schema-v4.1 four-decision micro-sessions. Labels, actor IDs,
bot families and provenance are absent. Old schemas and extra fields are
rejected before inference.

The resident model configured by `POKER44_MODEL_FACTORY=module:create_model`
returns one finite probability in `[0,1]` per item. Request byte/item limits and
validator hotkey authentication are enforced independently of model code.
Encrypted Axon commitments remain described in `encrypted-axon-endpoints.md`.
