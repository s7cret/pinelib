# Stage 4 local request support matrix

| Area | Local status | Evidence boundary |
|---|---|---|
| Strict provider protocol and capability admission | Supported | Contract and negative tests |
| Canonical bars, snapshots, coverage, revision/finality | Supported | Round-trip and mutation tests |
| Dataset key, registry, lineage, discovery, cursors | Supported | Identity/property/checkpoint tests |
| Historical `security` | Supported | Four-mode HTF local reference matrix |
| Realtime admitted/developing `security` | Supported | Discovery/no-refetch/reload tests |
| `request.security_lower_tf` | Supported | Ordered/full-containment/array tests |
| v5/v6 dynamic request policy | Supported locally | Adjacent-version differential tests |
| Capability-bound nested requests | Supported locally | Parent/cycle/depth/rollback tests |
| Scalar/tuple/array/UDT/map result shapes | Supported locally | Shape validation and round-trip tests |
| `ignore_invalid_symbol` taxonomy | Supported | Invalid-symbol vs other provider errors |
| `calc_bars_count` and resource ceilings | Supported | Provider assertion and limit tests |
| Incremental APPEND snapshot evaluation | Supported | Delta-state property and benchmark evidence |
| Checkpoint restore without refetch | Supported | Clean runtime restore test |
| `request.financial` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.economic` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.earnings` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.dividends` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.splits` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.currency_rate` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.seed` | Unsupported fail-closed | Provider/canonical contract unavailable |
| `request.footprint` | Unsupported fail-closed | Provider/canonical contract unavailable |

“Supported locally” means implemented and tested against deterministic local contract/reference vectors. It does not mean verified against sealed TradingView output or reconciled to the absent authoritative Pine2AST RC6 overload denominator.
