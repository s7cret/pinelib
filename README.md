# PineLib Runtime v0.2.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v0.2.0 advances the v1.4 runtime contract with a real P0 technical-analysis base
on top of the v0.1 core runtime.

Implemented through v0.2.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration and commit ownership
- `na`, `nz`, `fixnan`, inclusive `pine_range`, and Pine numeric/operator helpers
- `DataProvider` protocols and in-memory validated provider
- timezone/session-aware `time()` and `time_close()` scaffold using `zoneinfo`
- stateful and batch P0 TA helpers:
  - `ta.sma`, `ta.ema`, `ta.rma`, `ta.tr`, `ta.atr`, `ta.rsi`, `ta.macd`
  - `ta.highest`, `ta.lowest`, `ta.change`, `ta.cross`, `ta.crossover`, `ta.crossunder`
- math aliases: `pine_abs`, `pine_round`, `pine_min`, `pine_max`, `pine_sum`
- precision comparisons: `pine_isclose`, `pine_eq`, `pine_ne`, `pine_gt`, `pine_gte`, `pine_lt`, `pine_lte`
- pytest, ruff, black, mypy, compileall, release manifest, and reproducible archive support

## Install

```bash
pip install -e .[dev]
```

## Minimal runtime loop with TA

```python
from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo, ta

runtime = PineRuntime(
    symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
    timeframe=TimeframeInfo.from_string("60"),
    config=RuntimeConfig(),
)

bars = [
    Bar(time=1704067200000, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0),
    Bar(time=1704070800000, open=1.5, high=3.0, low=1.0, close=2.5, volume=12.0),
]

for bar in bars:
    runtime.begin_bar(bar)
    ema_value = ta.ema(runtime.close, 20, runtime=runtime, state_id="L10_C12_ema_1")
    ema_series = runtime.series("ema20", "float")
    ema_series.set_current(ema_value)
    runtime.end_bar()
```

## Coverage map for v0.2

- Core runtime: implemented
- Request/data access foundation: implemented without `request.security` expression execution
- Sessions/time helpers: implemented scaffold and contract tests
- P0 TA/runtime base: implemented with stateful runtime mode and batch consistency tests
- Broker emulator, inputs, visuals, full TA namespace, and golden TradingView parity suite:
  deferred beyond v0.2

Unsupported future features are not silently emulated; the runtime raises typed,
diagnostic-bearing errors where parity would otherwise be misleading.
