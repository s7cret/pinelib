# PineLib Runtime v0.3.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v0.3.0 advances the v1.4 runtime contract with runtime metadata, validated inputs,
and the first real `request.security` merge/execution foundation.

Implemented through v0.3.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration and commit ownership
- runtime metadata models: `syminfo`, enriched `timeframe`, and `barstate`
- `RuntimeConfig.diagnostics` collection for explicit runtime diagnostics
- `input.int/float/bool/string/timeframe/symbol/session/source` metadata and validation
- `na`, `nz`, `fixnan`, inclusive `pine_range`, and Pine numeric/operator helpers
- `DataProvider` protocols and in-memory provider with normalization metadata log
- timezone/session-aware `time()` and `time_close()` using IANA `zoneinfo`, including DST/overnight coverage
- `request.security` foundation:
  - precomputed or callable requested values
  - child runtime execution with isolated indicator state namespace
  - `barmerge.gaps_on/off` and `barmerge.lookahead_on/off` merge core over validated bars
  - explicit `PL_UNSUPPORTED_NESTED_SECURITY` diagnostic/error when nested requests are disabled
- stateful and batch P0 TA helpers:
  - `ta.sma`, `ta.ema`, `ta.rma`, `ta.tr`, `ta.atr`, `ta.rsi`, `ta.macd`
  - `ta.highest`, `ta.lowest`, `ta.change`, `ta.cross`, `ta.crossover`, `ta.crossunder`
- math aliases: `pine_abs`, `pine_round`, `pine_min`, `pine_max`, `pine_sum`
- precision comparisons: `pine_isclose`, `pine_eq`, `pine_ne`, `pine_gt`, `pine_gte`, `pine_lt`, `pine_lte`
- pytest, mypy, compileall, release manifest, and reproducible archive support

## Install

```bash
pip install -e .[dev]
```

## Minimal runtime loop with request.security

```python
from pinelib import Bar, InMemoryDataProvider, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo, security, ta

chart_bars = [
    Bar(time=1704067200000, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0),
    Bar(time=1704070800000, open=1.5, high=3.0, low=1.0, close=2.5, volume=12.0),
]
requested_bars = [
    Bar(time=1704067200000, time_close=1704074399999, open=10.0, high=11.0, low=9.0, close=10.5),
]
provider = InMemoryDataProvider({
    ("TEST:AAA", "60"): chart_bars,
    ("TEST:BBB", "120"): requested_bars,
})
runtime = PineRuntime(
    symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
    timeframe=TimeframeInfo.from_string("60"),
    data_provider=provider,
    config=RuntimeConfig(),
)

for bar in chart_bars:
    runtime.begin_bar(bar)
    htf_close = security(
        "TEST:BBB",
        "120",
        lambda request_rt: request_rt.close[0],
        runtime=runtime,
        state_id="L20_C8_security_1",
    )
    ema_value = ta.ema(runtime.close, 20, runtime=runtime, state_id="L10_C12_ema_1")
    runtime.series("ema20", "float").set_current(ema_value)
    runtime.series("htf_close", "float").set_current(htf_close)
    runtime.end_bar()
```

## Coverage map for v0.3

- Core runtime: implemented
- Inputs/runtime metadata: implemented foundation with validation diagnostics
- Request/data access foundation: implemented `request.security` merge and child runtime execution basics
- Sessions/time helpers: implemented scaffold with regular, overnight, and DST contract tests
- P0 TA/runtime base: implemented with stateful runtime mode and batch consistency tests
- Broker emulator, visuals, full TA namespace, and golden TradingView parity suite: deferred beyond v0.3

Unsupported future features are not silently emulated; the runtime raises typed,
diagnostic-bearing errors where parity would otherwise be misleading.
