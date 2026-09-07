# Stage 2: audited numeric bindings and rounding

This candidate repairs a bounded group of source-to-ABI bindings and numeric
semantics. It does not declare Stage 2 accepted or claim TradingView execution
parity. The manifest's `tradingview_compile_oracle.status` remains `NOT_RUN`.

## Independent contracts

- [TradingView v6 reference, math.round](https://www.tradingview.com/pine-script-reference/v6/#fun_math.round)
  defines rounding to the nearest integer with a tie choosing the greater
  integer. Omitting precision returns an int; supplying precision returns a
  float, including zero and negative precision. For example, rounding -1.25
  to one decimal place gives -1.2.
- [TradingView v6 reference, math.round_to_mintick](https://www.tradingview.com/pine-script-reference/v6/#fun_math.round_to_mintick)
  uses the symbol's minimum tick and the same tie rule.
- [TradingView v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)
  records the historical-to-modern parameter changes: `exp(x)` and `sqrt(x)`
  use `number` in the math namespace; `round(x, precision)` becomes
  `math.round(number, precision)`; `rsi(x, y)` becomes `ta.rsi(source, length)`.
  It also distinguishes the conventional RSI with a stable integer length
  from the historical ratio overload.
- [TradingView v4 release notes, April 2021](https://www.tradingview.com/pine-script-docs/v4/release-notes/#april-2021)
  introduce round's precision overload. The historical binding therefore
  admits its exact producer overload only in v4. One-argument round remains
  available in v1-v4.
- [TradingView v4 reference](https://in.tradingview.com/pine-script-reference/v4/)
  and [v6 reference](https://www.tradingview.com/pine-script-reference/v6/)
  define unchanged parameter spellings for pow, sma, wma and macd. MACD's
  fast, slow and signal lengths, and conventional RSI's length, are stable
  integer parameters. RSI uses Wilder smoothing of gains and losses.

## Runtime and target changes

`round_v1` uses `None` solely as its ABI omission marker, distinct from Pine
`na`. Both numeric rounding operations compare exact ratios of decimal input
representations; this avoids Python's ties-to-even rule and the previous
negative-tie error. Extreme precision does not allocate enormous decimal
powers when it cannot change the result.

The existing two-argument `round_to_mintick_v1` remains callable. Generated
source calls target the additive `round_to_mintick_context_v1`, which reads
mintick from the active transaction's injected instrument context. Missing
instrument context and a closed transaction fail explicitly.

The additive `pinelib.abi.primitives.float_v1(x)` delegates to
`pinelib.core.values.pine_float`, sharing `require_number` and canonical Pine
`na` with the existing value owner. The [float reference contract](https://www.tradingview.com/pine-script-reference/v6/#fun_float)
accepts numeric arguments, including typed missing values. The target has an
exact global-function binding in v1-v6. It preserves canonical `na`, converts
finite ints/floats and rejects bool, string, Python `None`, raw nonfinite
floats and foreign objects. Generated Pine `na` is already canonical; the
operator compatibility translation of Python `None` is not applied to casts.

The frozen `official_pine_v6_surface.json` and its source hashes are unchanged.
The builder overlays only audited signatures. The official row count retains
its original denominator. `historical_call_bindings` is a separate additive
table for abs, ceil, floor, exp, round, sqrt, pow, sma, wma, macd and conventional rsi, with
explicit producer call forms, versions and overload identities. Historical
round has two entries because its precision overload begins in v4. The
historical RSI ratio overload has no target binding in this wave.

The final integration correction aligns abs, ceil and floor with the producer's
audited `number` parameter in v5-v6 and historical `x` in v1-v4. Ceil and floor
return int; abs preserves an int or float input's type, with the exact integer
producer overload admitted alongside its existing canonical float overload.
These corrections change manifest metadata only; their existing numeric kernels
remain unchanged. The legacy version ranges come from the existing catalog.

Argument aliases are function-specific. Neither a coincidental Python
parameter name nor an unknown source name authorizes a binding. Modern
namespace calls and historical global calls carry distinct exact call forms.

## Verification and corrected prior assertion

`tests/test_builtin_numeric_contracts.py` checks signed ties and adjacent
values, result types, NA and invalid inputs, context admission, source names,
version limits, complete ABI parameter binding and overload separation.
`tests/test_builtin_stateful_oracles.py` uses hand-derived RSI gain/loss
fractions and MACD values after a constant baseline, including historical
bars, realtime recalculation, abort and JSON checkpoint restore. MACD's
constant baseline deliberately makes both EMA seed conventions coincide;
these tests do not establish the disputed initial warmup behavior.

Exactly one pre-existing assertion changes:
`tests/test_stage3_math_string_time_input.py::test_math_na_domains_rounding_and_varargs`
expected `round_v1(-1.25, 1)` to equal -1.3. The independently documented tie
rule requires -1.2. The old assertion was run against the corrected runtime
and failed before it was edited. No test was deleted, skipped or weakened.

Local evidence, kept outside the release payload in `.validation/`:

- `builtin-numeric-baseline.log`: the initial new numeric/binding suite against
  baseline `ad235a8`, 26 failed and 22 passed.
- `builtin-numeric-initial-fix.log`: 52 passed and the one obsolete negative-tie
  assertion failed before its correction.
- `builtin-py311.log/xml` and `builtin-py313.log/xml`: final runtime suite results.
- `float-cast-baseline.log`: the new cast suite before implementation, 13
  failed and 1 passed; `tests/test_float_cast_abi.py` now has 14 passing cases.
- `builtin-float-py311.log/xml` and `builtin-float-py313.log/xml`: combined
  follow-up suite, with 573 collected cases. The official denominator remains
  1108; direct targets increase from 242 to 243 and unsupported rows decrease
  from 527 to 526. No historical alias rows or frozen source identities change
  in the cast follow-up.
- `unary-binding-baseline.log`: 18 failures before the final abs/ceil/floor
  binding correction. `tests/test_audited_unary_math_bindings.py` now covers all
  six versions with positive, NA and invalid-type inputs. The final inventory
  is 591 tests, including 108 new tests in this bounded numeric wave; the
  historical table contains 12 entries. Official classification counts remain
  1108 total, 243 direct, 339 delegated and 526 unsupported. The affected numeric
  and manifest checks are repeated locally; the next full run is the Linux CI
  candidate run.

EMA initialization and general NA/bool semantics still need separate,
version-exact independent evidence. In particular, the v4 reference's EMA
example initializes from an SMA, while modern descriptions require a fresh
audit. No EMA or other TA kernel implementation changes are included here.
