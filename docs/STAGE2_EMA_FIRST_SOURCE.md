# EMA/MACD first-source state profile

This bounded Stage 2 change applies to `ta.ema` and all three internal EMA states
of `ta.macd` in Pine versions 5 and 6. The existing EMA step uses the first
defined source as its initial value, then applies `alpha = 2 / (length + 1)`.
For `[1, 2, 3, 4, 5]` and length 3 the trajectory is
`[1, 3/2, 9/4, 25/8, 65/16]`.

The versioned TradingView EMA reference example uses the source when the prior
EMA is missing. Both versioned primers demonstrate that MACD is the fast EMA
minus the slow EMA, the signal is an EMA of that difference, and the histogram
is the difference between those two outputs. Primary references:

- [Pine v5 EMA reference](https://www.tradingview.com/pine-script-reference/v5/#fun_ta.ema)
- [Pine v6 EMA reference](https://www.tradingview.com/pine-script-reference/v6/#fun_ta.ema)
- [Pine v5 first indicator](https://www.tradingview.com/pine-script-docs/v5/primer/first-indicator/)
- [Pine v6 first indicator](https://www.tradingview.com/pine-script-docs/primer/first-indicator/)

The test fixture `recursive_ta_manual_expected.json` preserves the independently
authored 33-row table (SHA256
`19b562cd1d7b37af215bbb300014b4e728b1efbce01cddf384fcc775ae2ced29`).
Twenty rows have eligible expectations: seven EMA, six unchanged RSI controls,
and seven MACD. Thirteen rows retain `expected: null`; their candidate values
are not used as an oracle. General internal-NA-gap timing and TSI initialization
remain unverified. The separate TSI scaling finding is outside this change.

## Numerical checkpoint boundary

Modern EMA and MACD slots use `ta.ema.state.v2` and `ta.macd.state.v2`, respectively,
with the mandatory literal `profile: "ema_first_source_v1"`. Slot payloads are
closed and constant in size. Every retained numerical value is an exact finite
float; lengths are exact positive integers. An unseeded EMA omits `value`.
MACD has `fast`, `slow`, and `signal` substates, each either empty or containing
one `value`; these three states seed together. Initial uncommitted baselines
contain only the kernel identity and profile. Parameters cannot change between
committed and working portions, and a committed seed cannot disappear from
working state.

For Pine 5/6, old affected `.state.v1` checkpoints fail with a diagnostic requiring
replay from the original input. The old SMA-seeded numerical state cannot be
converted by changing its schema label. The shared scratch decoder enforces the
same rule for root state, compiled request children, and every pending-abort
transition witness before replacing any live state. Validation does not execute
providers, scripts, or callbacks. Ordinary outer checkpoint and transcript
schemas are unchanged; this is an explicit TA slot revision.

Integrity hashes establish consistency of supplied state, not proof that the
source executed it. In particular, unseeded committed state plus newly seeded
working state is valid after an all-NA history followed by a first defined
realtime trial. Admission must accept that transition. The existing aggregate
checkpoint budget also includes the new constant-size payloads and witnesses.

## Compatibility and verification scope

Pine 1–4 EMA/MACD, RMA, KC, KCW, and TSI retain their existing seed behavior and
state revisions. They share the same private EMA step; its default remains the
legacy seed. Public ABI adapters, manifest, availability, source catalog,
capabilities, and language-version resolution are unchanged. Native callers
must honor this explicit numerical state boundary; host admission additionally
binds checkpoints to the complete exact component source identity.

The legacy fixture contains 52 genuine checkpoints captured from PineLib
`2148bca8370858ef8f7716ee0ba27d42960563b4` before this implementation, including
full/compact state, retained abort state, and actual compiled request children.
Tests cover the complete eligible trajectories, speculative callbacks, abort and
same-sequence retry, deferred historical fill callbacks and final publication,
JSON checkpoint continuation, closed-state mutations, and atomic late-child
rejection. A single previous test literal for modern EMA is corrected separately
using independently reviewed rational arithmetic; its original failure is
preserved in the publication evidence.

These results do not accept all of Stage 2 or claim parity for the full TA family.
