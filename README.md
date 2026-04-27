# PineLib Runtime v0.5.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v0.5.0 continues the v1.4 runtime contract / TZ_01 track with Bar Magnifier execution provenance plus visual/reference foundations.

Implemented through v0.5.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration, commit ownership, recalculation guard scaffold, inputs, metadata, and diagnostics
- `DataProvider` / `IntrabarDataProvider` protocols and in-memory provider
- timezone/session-aware `time()` and `time_close()` helpers
- `request.security` foundation with explicit nested-request diagnostics
- P0 TA helpers and Pine numeric/operator helpers
- `StrategyContext` broker emulator MVP from v0.4.0
- Bar Magnifier foundation:
  - provider-backed intrabar path when `use_bar_magnifier=True`
  - strict missing-data error `PL_MISSING_INTRABAR_DATA`
  - non-strict warning fallback `PL_WARNING_BAR_MAGNIFIER_FALLBACK`
  - `fill_source` provenance (`intrabar` / `ohlc_path`) on fills and closed trades
  - TP/SL bracket arbitration by earliest crossing in the active path
- `calc_on_every_tick` historical fallback diagnostic `PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK`
- visual recorder foundation with stable `PineObjectId` for label/line/box/table lifecycle, set/delete events, and count limits
- reference container foundation: `PineArray`, `PineMap`, `PineMatrix`, and explicit `PL_REFERENCE_HISTORY_UNSUPPORTED`

## Install

```bash
pip install -e .[dev]
```

## Minimal strategy loop

```python
from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo

bars = [
    Bar(time=1704067200000, open=10, high=11, low=9, close=10),
    Bar(time=1704070800000, open=12, high=13, low=11, close=12),
]
runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
strategy = StrategyContext(default_qty_type="fixed", default_qty_value=1)
strategy.attach_runtime(runtime)

for i, bar in enumerate(bars):
    runtime.begin_bar(bar)
    if i == 0:
        strategy.entry("L", "long")
    strategy.process_orders_for_bar(runtime=runtime, bar=bar)
    runtime.end_bar()

assert strategy.position_size == 1
assert strategy.position_avg_price == 12
assert strategy.fills[-1].fill_source == "ohlc_path"
```

## Coverage map for v0.5

- Core runtime, inputs, request/security, sessions/time helpers, P0 TA base: implemented foundation
- Strategy broker emulator: MVP plus Bar Magnifier provider path and fill provenance
- Visual/reference types: deterministic recorder and minimal identity/copy foundations
- Deferred: full TradingView Bar Magnifier parity matrix, realtime tick execution, full visual API/rendering, full reference history semantics, trailing exits, advanced margin/leverage, and complete golden TradingView parity suite
