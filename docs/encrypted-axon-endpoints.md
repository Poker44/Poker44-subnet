# Encrypted Axon Endpoints

Poker44 supports opt-in encrypted endpoint commitments to reduce public exposure
of miner origin IP addresses.

## Security Model

When protection is enabled:

1. the miner encrypts a versioned, hotkey-bound `IPv4:port` payload with the
   Poker44 endpoint public key;
2. the miner publishes the ciphertext through Bittensor commitment metadata;
3. the miner reads the finalized commitment back from chain and requires an
   exact ciphertext match;
4. only after that verification succeeds, the miner advertises a non-routable
   placeholder endpoint in the metagraph;
5. updated validators decrypt the commitment and query a local copy of the Axon
   using the recovered endpoint.

The encrypted payload is bound to the miner hotkey. A commitment copied from a
different hotkey is rejected. Validators also reject private, loopback,
documentation-only, malformed, and out-of-range endpoints.

The mechanism hides the origin from public metagraph readers. It does not hide
the origin from authorized validators and does not replace upstream DDoS
scrubbing.

## Compatibility

Protection is disabled for miners unless explicitly enabled. Public miners keep
using their existing metagraph endpoints.

Validators without a configured decryption key keep their existing behavior for
public miners. They cannot contact protected miners, so miners must not opt in
until Poker44 confirms that the active validator set has upgraded.

If commitment publication fails, the miner keeps its public endpoint. It never
switches to the placeholder endpoint on an unconfirmed or unreadable
publication.

An encrypted commitment is used only while the miner advertises Poker44's
masked endpoint. If the miner later returns to a public Axon, validators ignore
the old commitment and use the public metagraph endpoint.

## Rollout Status

The active scoring validator set supports protected endpoints and reports the
expected key fingerprint. The subnet public key is available in the current
release, but miner protection remains opt-in and disabled by default.

Miners should activate one at a time and confirm finalized commitment and
metagraph state before retiring the previous origin. Enabling protection
against an outdated validator set can make a miner unreachable.

## Canary Safety Checks

Subnet 126 currently enforces a 50-block Axon serving rate limit. Before moving
the controlled canary to a new origin, confirm that at least 50 blocks have
passed since its last Axon update. Starting the migration sooner can leave the
old public endpoint on-chain until the rate limit expires.

Keep the previous origin available throughout the canary. Do not treat a
successful process start or commitment publication as proof that masking is
active. Confirm all of the following independently:

1. the finalized commitment read-back exactly matches the ciphertext published
   by the canary;
2. the finalized metagraph advertises `192.0.2.1:1234` for the canary hotkey;
3. every scoring validator reports the expected key fingerprint, a successful
   commitment refresh, and the canary in its protected-miner count;
4. every scoring validator completes a signed request to the canary through the
   resolved endpoint;
5. a normal score report from the canary reaches the backend without changing
   scoring, coverage, latency, or weight behavior for public miners.

Abort the rollout if any validator cannot resolve or query the canary. Keep the
new origin online, wait for the Axon serving rate limit when necessary, remove
the miner protection settings, advertise the new public endpoint again, and
confirm that finalized metagraph read-back before considering rollback
complete. A local restart alone is not proof of rollback.

## Miner Activation

Update dependencies and set:

```bash
export POKER44_ENCRYPTED_AXON_ENABLED=true
export POKER44_AXON_EXTERNAL_IP=<new_public_ipv4>
export POKER44_AXON_EXTERNAL_PORT=<axon_port>
```

Subnet 126 includes the endpoint public key in the release. The
`POKER44_ENDPOINT_PUBLIC_KEY` setting remains available only as an explicit
override.

After Poker44 confirms validator readiness, a miner whose previous IP has
already been exposed should move to a new origin IP before the protected
restart. Keep the old origin available until the canary checks above have
completed.

## Validator Activation

Updated validators provision the resolver key automatically. Each validator
generates an ephemeral Curve25519 transport key and signs the provisioning
request with its Bittensor hotkey. The backend requires current validator
permit/stake plus Poker44's explicit scoring-validator allowlist, rejects replay,
and returns the resolver key only inside a transport-key-encrypted envelope.

The validator verifies the release fingerprint before accepting the key and
stores an atomic owner-only cache in its neuron state directory. A backend
outage therefore does not remove an already provisioned validator's ability to
resolve protected miners.

No operator key installation is required. The previous file configuration
remains available as an override:

```bash
install -m 600 /secure/source/poker44-endpoint.key /etc/poker44/endpoint.key
export POKER44_ENDPOINT_PRIVATE_KEY_FILE=/etc/poker44/endpoint.key
export POKER44_ENDPOINT_REFRESH_SECONDS=300
```

`POKER44_ENDPOINT_PRIVATE_KEY` remains available for compatibility, but the file
setting is preferred because process managers can expose environment values.
Configure only one of the two settings.

The resolver supports mixed public and protected miners. Commitment RPC
failures retain the last valid endpoint cache. Runtime reports expose only
resolver readiness, key source, the public-key fingerprint, refresh status, and
protected miner count; they never expose endpoint addresses or private-key
material.
