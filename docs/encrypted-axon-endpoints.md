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

## Rollout Gate

Shipping resolver code does not authorize miners to enable protection. Poker44
must complete these steps in order:

1. deploy the resolver to the active validator set with miner protection still
   disabled;
2. verify matching key fingerprints and successful commitment refresh status
   in validator runtime reports;
3. validate one controlled canary miner end to end;
4. explicitly announce that miner activation is available.

Enabling protection before this gate is complete can make a miner unreachable
to validators that have not upgraded.

## Miner Activation

Update dependencies and set:

```bash
export POKER44_ENCRYPTED_AXON_ENABLED=true
export POKER44_AXON_EXTERNAL_IP=<new_public_ipv4>
export POKER44_AXON_EXTERNAL_PORT=<axon_port>
```

During the validator-readiness phase, Poker44 provides
`POKER44_ENDPOINT_PUBLIC_KEY` only to controlled canary miners. A subnet default
will be published only after the rollout gate is complete.

After Poker44 confirms validator readiness, a miner whose previous IP has
already been exposed should move to a new origin IP before the protected
restart.

## Validator Activation

Validators receive `POKER44_ENDPOINT_PRIVATE_KEY` through the private operator
channel. The key must be stored only in the validator environment and must
never be committed, logged, or placed in process arguments.

```bash
export POKER44_ENDPOINT_PRIVATE_KEY=<privately_distributed_key>
export POKER44_ENDPOINT_REFRESH_SECONDS=300
```

The resolver supports mixed public and protected miners. Commitment RPC
failures retain the last valid endpoint cache. Runtime reports expose only
resolver readiness, the public-key fingerprint, refresh status, and protected
miner count; they never expose endpoint addresses or private-key material.
