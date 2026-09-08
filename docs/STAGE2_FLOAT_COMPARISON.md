# Bounded Pine v6 float comparisons

The shared `core.values.pine_binary` operator now applies the current Pine v6
comparison precision rule. All six numeric comparisons round float-domain
operands to nine fractional digits. A mixed int/float pair enters the float
domain through the existing `pine_float` value owner before comparison. Pure
integer pairs retain exact integer comparison. Finite-number validation rejects
nonfinite native floats, and unrepresentable mixed integer conversions report
the existing value-domain error.

The [current type-system documentation](https://www.tradingview.com/pine-script-docs/language/type-system/#float)
establishes the precision and mixed-domain rules. Its NA section specifies false
for every comparison with an NA-valued variable, including inequality. The v6
operator follows that rule after existing enum type validation. These native
tests pass canonical NA values; they do not certify a bare `na` literal as valid
comparison source syntax.

The [v5 documentation](https://www.tradingview.com/pine-script-docs/v5/language/type-system/)
does not establish the new precision rule. Versions 1–5 preserve prior runtime
behavior. Legacy expected values are compatibility controls, not new TradingView
parity claims. Bool equality, strings and pure integer comparisons preserve their
existing owners; invalid bool ordering still rejects. Mixed bool/number equality
is outside this bounded change and is not certified by these tests.

## Midpoint policy and evidence limits

Runtime rounding uses Python `round(actual_binary_float, 9)`. This gives a defined
result for every admitted finite operand, including exact binary midpoints. Its
tie behavior is an explicit local policy; TradingView midpoint parity remains
**UNVERIFIED**. Four separate local-policy tests cover signed `1/1024` and `3/1024`
midpoints. They are not part of the independent Pine expected table. The
separately documented `math.round` tie rule is not used as comparison authority.

`tests/fixtures/float_comparison_manual_expected.json` was manually authored
before semantic SUT execution. SHA256:
`19ecb5d3fbdc4229b01110b7cbecd0419e6eb9f9d11530b2b19308350d80f8a1`.
Its 26 non-midpoint numeric pairs cover signed near-boundary values, fractional
large values, mixed casting beyond 2**53, pure integer precision, subnormals,
signed zero and large finite equality. Six operator expectations per pair are
literal values. It also records native NA and bool controls. It is not a
TradingView export and does not establish complete language parity.

## Validation and compatibility

The new owner suite has 1119 tests. It covers versions 1–6, direct value and
transaction ABI paths, invalid native values, and actual historical/realtime
trial/abort/same-sequence retry with full and compact JSON checkpoints. Restored
operand values, boolean result history and continuation checkpoints are checked.
Generated-source integration remains a separate compiler/host proof.

On the exact baseline `d33fdea2ff3d2fa3c567c2c83da08664c8937fc1`, the final new
suite has 103 failures and 1016 passes on both Python 3.11 and 3.13. With this
change, all 1119 pass. The complete runtime suite has 3129 passes and three
existing Windows release-tool failures on both interpreters. Those same three
failures reproduce independently against the unchanged baseline; all old tests
and assertions are retained. Linux joint validation is still required.

There is one production file change, with no ABI/catalog/capability or checkpoint
schema change. Version context still comes from the admitted RuntimeSession.
Restore does not rewrite stored historical results. Publication must identify
the exact new runtime revision. Full Stage2 acceptance remains false.
