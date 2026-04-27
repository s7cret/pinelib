# PineLib Runtime v1.0.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v1.0.0 is the first stable release for `runtime_contract_v1.4` / `TZ_01`: the public API surface is reviewed, packaging is typed, release artifacts are reproducible, and known parity limits are documented explicitly.

Implemented through v1.0.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- stable reviewed public top-level API surface via `pinelib.__all__`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration, commit ownership, recalculation guard scaffold, inputs, metadata, and diagnostics
- `DataProvider` / `IntrabarDataProvider` protocols and in-memory provider
- timezone/session-aware `time()` and `time_close()` helpers with IANA DST coverage
- `request.security` foundation with merge modes, child runtime isolation, and explicit nested-request diagnostics
- StrategyContext broker emulator MVP with market/limit/stop/stop-limit orders, exit reservations/OCA reduce, sizing, commission/slippage, Bar Magnifier provenance, and guarded `calc_on_order_fills`
- bar-by-bar `run_generated_strategy()` helper for generated-like strategy classes using `PineRuntime` + `StrategyContext`
- result snapshots, JSON-safe backtest report schema, golden-compare tolerance utility, strategy/equity compare reports, and optimizer-friendly params metadata capture
- CSV OHLCV loader plus optional Parquet loader with graceful dependency errors
- TradingView-exported indicator/trade CSV fixture loaders and sample contract scaffolding
- visual recorder foundation and reference containers (`PineArray`, `PineMap`, `PineMatrix`)
- TA helpers: `sma`, `ema`, `rma`, `rsi`, `macd`, `tr`, `atr`, `highest`, `lowest`, `change`, crosses, plus the v0.6 extended helper set
- namespace helpers: expanded `pinelib.math`, basic `pinelib.string`, and basic `pinelib.color`
- `py.typed`, mypy strict-ish package gate, CI workflow, release checklist, migration guide, final audit, and performance smoke tests

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
from pinelib import load_bars, load_bars_csv

bars = load_bars_csv("bars.csv")      # required: time, open, high, low, close
bars2 = load_bars("bars.parquet")     # optional pandas + pyarrow/fastparquet
```

## Gates

```bash
python -m compileall pinelib tests scripts
pytest -q
mypy pinelib
python scripts/build_release.py
```

## Coverage and limitations

v1.0.0 does **not** claim full TradingView parity. Unsupported or incomplete areas are explicit diagnostics/errors, not silent approximations.

Start here:

- `docs/public_api_v1_0_0.md`
- `docs/semantic_versioning_policy.md`
- `docs/coverage_map_v1_0_0.md`
- `docs/migration_v0_9_to_v1_0.md`
- `docs/release_checklist_v1_0_0.md`
- `FINAL_AUDIT_v1.0.0.md`
