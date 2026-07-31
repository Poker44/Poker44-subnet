# Validator

The validator polls one manually published v4.1 micro-session window. Every
validator receives the same immutable ordering and verifies its dataset hash.
It queries every eligible reachable miner hotkey; shared coldkeys are not
deduplicated.

Quality is `0.50 * AP skill + 0.30 * recall@5% FPR + 0.20 * Brier skill`.
Highest positive finite quality wins, with ascending UID as the exact-tie
breaker. The transition target assigns `POKER44_BURN_FRACTION` (default 90%)
to the live subnet owner hotkey, `POKER44_FUNDING_FRACTION` (default 5%) to
`POKER44_FUNDING_HOTKEY`, and the remainder to the winner. The funding hotkey
must be registered and different from the owner. Only a new valid round changes
the target.
The same target is refreshed every `POKER44_WEIGHT_REFRESH_BLOCKS` (default
720), subject to the chain rate limit and commit-reveal lifecycle.

If the winning hotkey disappears, settlement blocks instead of silently
promoting the runner-up. Signed dashboard events expose every miner score and
binary round reward, while `weights_refreshed` is distinct from a new round.
