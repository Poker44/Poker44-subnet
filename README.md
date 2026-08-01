# Poker44 subnet

Poker44 evaluates bot probability from manually published, immutable
schema-v4.1 tournament micro-session windows. Labels and private actor groups
remain inside each validator.

Validators poll the platform, verify the complete ordered window, query every
eligible reachable miner hotkey through `MicroSessionDetectionSynapse`, compute
a continuous quality score and select one deterministic winner. During the
transition, the target assigns 90% to the live subnet owner, 5% to the
configurable tournament-funding hotkey and 5% to that winner. The unchanged
target is refreshed every 720 blocks without re-evaluating miners. There is no
EMA, historical request, repository check, coldkey deduplication or legacy
evaluation track.

Run `PYTHONPATH=. pytest -q`. See `docs/validator.md`, `docs/miner.md` and
`docs/tournament-evaluation-workflow.md` for the operational contract. The
deployed miner target is release `0.2.1` on `main`; old `dev` documentation and
the retired hand-chunk benchmark are not compatible with this contract.
