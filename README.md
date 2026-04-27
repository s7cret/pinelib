# PineLib Runtime v0.6.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v0.6.0 continues the v1.4 runtime contract / TZ_01 track with extended TA coverage and basic `math`, `string`, and `color` namespaces.

Implemented through v0.6.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration, commit ownership, recalculation guard scaffold, inputs, metadata, and diagnostics
- `DataProvider` / `IntrabarDataProvider` protocols and in-memory provider
- timezone/session-aware `time()` and `time_close()` helpers
- `request.security` foundation with explicit nested-request diagnostics
- StrategyContext broker emulator MVP plus Bar Magnifier provenance from v0.5.0
- visual recorder foundation and reference containers (`PineArray`, `PineMap`, `PineMatrix`)
- TA helpers: `sma`, `ema`, `rma`, `rsi`, `macd`, `tr`, `atr`, `highest`, `lowest`, `change`, crosses, plus v0.6 additions: `bb`, `bbw`, fast `stoch`, `dmi`/`adx`, `supertrend`, `wma`, `vwma`, `hma`, `swma`, `alma`, `sar`, `pivot_high`/`pivot_low`, `valuewhen`, `barssince`, `linreg`, `variance`, `stdev`, `dev`, percentile/percentrank basics, `vwap`, `mfi`, `cci`, `obv`, `mom`, `roc`, `correlation`, `rising`, and `falling`
- namespace helpers: expanded `pinelib.math`, basic `pinelib.string`, and basic `pinelib.color`

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

## Coverage map for v0.6

- Batch and runtime modes are preserved for existing stateful indicators; runtime stateful helpers require explicit `state_id`.
- Several new TA helpers are batch-first; incomplete overloads raise explicit `PineRuntimeError` instead of silently approximating.
- Deferred: full TradingView TA overload matrix, complete visual API/rendering, full reference history semantics, realtime tick execution, advanced strategy parity, and golden TradingView parity suite.
