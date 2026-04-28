# PineLib Runtime v1.0.1

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v1.0.1 is the current stable release for `runtime_contract_v1.4` / `TZ_01`: the public API surface is reviewed, packaging is typed, release artifacts are reproducible, and known parity limits are documented explicitly.

Stack train metadata: `pain-stack-pine-v6-2026.04-r1`, `pine_language_version=6`, `pine_docs_baseline=2026-04`, `runtime_contract=1.4` (see `RELEASE_STACK_MANIFEST_2026_04_R1.json`). This stack supports a verified Pine v6 subset/oracle snapshot; it does **not** claim full Pine v6 runtime parity. April 2026 language-relevant scope note: UDT collection sorting via `sort_field` for `array.sort`, `array.sort_indices`, and `matrix.sort`; Pine Editor word-wrap is non-runtime UX.

## Release scope and stack boundaries

`pinelib` is the runtime foundation used by AST2Python-generated modules. It owns Pine-style series/history behavior, runtime metadata, selected namespace helpers, visual recording scaffolds, data-provider protocols, and the current strategy-context broker emulator MVP documented below. It does **not** include an independent production Backtest Engine package, portfolio/research orchestration, parameter optimization, or TradingView-complete runtime parity.

Future Backtest Engine and Optimizer work is intentionally separate from this v1.0.1 runtime package and from the current `pain-stack-pine-v6-2026.04-r1` claim. If those packages are introduced later, they should consume PineLib through explicit runtime/BacktestRunner contracts rather than being represented as implemented PineLib scope.

Implemented through v1.0.1:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- stable reviewed public top-level API surface via `pinelib.__all__`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration, commit ownership, recalculation guard scaffold, inputs, metadata, and diagnostics
- `DataProvider` / `IntrabarDataProvider` protocols and in-memory provider
- timezone/session-aware `time()` and `time_close()` helpers with IANA DST coverage and explicit unsupported diagnostics for non-chart timeframe aggregation
- `request.security` foundation with merge modes, child runtime isolation, and explicit nested-request diagnostics
- StrategyContext broker emulator MVP with market/limit/stop/stop-limit orders, exit reservations/OCA reduce, sizing, commission/slippage, strict Bar Magnifier intrabar validation/provenance, guarded `calc_on_order_fills`, and supplied realtime tick execution
- bar-by-bar `run_generated_strategy()` helper for generated-like strategy classes using `PineRuntime` + `StrategyContext`
- result snapshots, JSON-safe backtest report schema, golden-compare tolerance utility, strategy/equity compare reports, and optimizer-friendly params metadata capture
- CSV OHLCV loader plus optional Parquet loader with graceful dependency errors
- TradingView-exported indicator/trade CSV fixture loaders plus oracle-ready fixture scaffolding; no local fixture is claimed as TradingView-verified without exported evidence
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
python scripts/run_tv_golden_suite.py
python scripts/build_release.py
python scripts/check_release_integrity.py RELEASE_MANIFEST_v1_0_1.json --require-head
python scripts/check_release_artifact_selftest.py pinelib_runtime_v1_0_1.zip
```

## License

MIT. See `LICENSE`.

## Coverage and limitations

v1.0.1 does **not** claim full TradingView parity. Unsupported or incomplete areas are explicit diagnostics/errors, not silent approximations. TradingView oracle-exportable cases are verified under `fixtures/tradingview`; supplied-tick parity is platform-blocked because TradingView exposes no deterministic tick-stream oracle/export.

Start here:

- `docs/public_api_v1_0_0.md`
- `docs/semantic_versioning_policy.md`
- `docs/coverage_map_v1_0_1.md`
- `docs/migration_v0_9_to_v1_0.md`
- `docs/release_checklist_v1_0_0.md`
- `FINAL_AUDIT_v1.0.1.md`
