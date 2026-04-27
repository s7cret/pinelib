# PineLib Runtime v0.8.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v0.8.0 continues the v1.4 runtime contract / TZ_01 track with TradingView parity fixture harnesses and target strategy integration scaffolding.

Implemented through v0.8.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration, commit ownership, recalculation guard scaffold, inputs, metadata, and diagnostics
- `DataProvider` / `IntrabarDataProvider` protocols and in-memory provider
- timezone/session-aware `time()` and `time_close()` helpers
- `request.security` foundation with explicit nested-request diagnostics
- StrategyContext broker emulator MVP plus Bar Magnifier provenance from v0.5.0
- v0.7 bar-by-bar `run_generated_strategy()` helper for generated-like strategy classes using `PineRuntime` + `StrategyContext`
- result snapshots, JSON-safe backtest report schema, golden-compare tolerance utility, strategy/equity compare reports, and optimizer-friendly params metadata capture
- CSV OHLCV loader plus optional Parquet loader with graceful dependency errors
- TradingView-exported indicator/trade CSV fixture loaders and indicator column compare reports in `pinelib.parity`
- AVAX/SOL/XLM sample integration scaffolding with placeholder data contracts in `docs/sample_contracts_v0_8_0.json`
- improved strategy schedule helper with guarded `calc_on_order_fills` recalc loop and runtime `process_orders_on_close` coverage
- visual recorder foundation and reference containers (`PineArray`, `PineMap`, `PineMatrix`)
- TA helpers: `sma`, `ema`, `rma`, `rsi`, `macd`, `tr`, `atr`, `highest`, `lowest`, `change`, crosses, plus v0.6 additions: `bb`, `bbw`, fast `stoch`, `dmi`/`adx`, `supertrend`, `wma`, `vwma`, `hma`, `swma`, `alma`, `sar`, `pivot_high`/`pivot_low`, `valuewhen`, `barssince`, `linreg`, `variance`, `stdev`, `dev`, percentile/percentrank basics, `vwap`, `mfi`, `cci`, `obv`, `mom`, `roc`, `correlation`, `rising`, and `falling`
- namespace helpers: expanded `pinelib.math`, basic `pinelib.string`, and basic `pinelib.color`

## Install

```bash
pip install -e .[dev]
```

## Generated strategy runner

```python
from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo, run_generated_strategy

class GeneratedLikeStrategy:
    params = {"qty": 1}
    INPUT_METADATA = {"qty": {"title": "Quantity", "type": "float", "default": 1}}

    def on_bar(self, runtime, strategy):
        if runtime.bar_index_series.current == 0:
            strategy.entry("L", "long", qty=self.params["qty"])

bars = [
    Bar(time=1704067200000, open=10, high=11, low=9, close=10),
    Bar(time=1704070800000, open=12, high=13, low=11, close=12),
]
runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
strategy = StrategyContext(default_qty_type="fixed", default_qty_value=1)

result = run_generated_strategy(GeneratedLikeStrategy(), runtime, strategy, bars)
assert strategy.position_size == 1
assert strategy.position_avg_price == 12
assert result.report.params_metadata["qty"]["default"] == 1
```

## Parity fixture harness

```python
from pinelib import compare_strategy_reports, load_tradingview_indicator_csv

fixture = load_tradingview_indicator_csv("tradingview_indicators.csv")
report = compare_strategy_reports(actual_report, expected_report, fields=["final_equity", "netprofit"], abs_tol=1e-4)
assert report.matches
```

## Bar file IO

```python
from pinelib import load_bars_csv, load_bars

bars = load_bars_csv("bars.csv")      # required: time, open, high, low, close
bars2 = load_bars("bars.parquet")     # optional pandas + pyarrow/fastparquet
```

## Coverage map for v0.8

- Batch and runtime modes are preserved for existing stateful indicators; runtime stateful helpers require explicit `state_id`.
- Backtest and parity compare reports are JSON-safe integration artifacts, not a complete TradingView strategy tester clone.
- Several TA helpers remain batch-first; incomplete overloads raise explicit `PineRuntimeError` instead of silently approximating.
- Deferred: full TradingView TA overload matrix, complete visual API/rendering, full reference history semantics, realtime tick execution, trailing-exit ratchets, margin calls, and advanced strategy parity.

See `docs/current_limitations.md` and `docs/coverage_map_v0_8_0.md` for current limitations and namespace coverage.
