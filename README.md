# PineLib

PineLib is the Python runtime foundation used by AST2Python-generated Pine-compatible modules. It provides the runtime objects, helper namespaces, diagnostics, and data contracts that generated code needs to execute deterministically in Python.

## What It Supports

- Pine-style `Series[T]` history with current vs committed bar semantics.
- `PineRuntime` bar loop metadata, bar-index/time tracking, inputs, diagnostics, and commit lifecycle.
- `Bar`, symbol, timeframe, and runtime metadata models with UTC millisecond timestamps.
- `StrategyContext` order-intent APIs for generated strategies: entry, exit, close, cancel, and risk intent recording.
- `run_generated_strategy()` for intent-only bar-by-bar execution of generated strategy classes.
- `DataProvider` and `IntrabarDataProvider` protocols with in-memory helpers.
- Time/session helpers including `time()` and `time_close()` with timezone-aware behavior.
- `request.security` foundation with merge modes, child runtime isolation, and explicit diagnostics for unsupported nested behavior.
- OHLCV CSV loading plus optional Parquet loading when pandas/Parquet dependencies are installed.
- Pine reference containers: `PineArray`, `PineMap`, and `PineMatrix`.
- Visual recording scaffolds for generated plot/label/table-style outputs.
- TA helpers including `sma`, `ema`, `rma`, `rsi`, `macd`, `tr`, `atr`, `highest`, `lowest`, `change`, and crossover/crossunder helpers.
- Namespace helpers under `pinelib.math`, `pinelib.string`, and `pinelib.color`.
- Typed package metadata via `py.typed`.

## Boundaries

PineLib owns generated-code runtime behavior. It does not parse Pine source, generate Python code, fetch market data from exchanges, optimize strategy parameters, or act as the final broker/fill/equity authority.

The surrounding OpenPine stack keeps those responsibilities split:

- `pine2ast`: Pine source to normalized AST JSON.
- `ast2python`: AST JSON to Python code targeting PineLib.
- `backtest_engine`: broker/fill/equity authority for historical backtests.
- `marketdata-provider`: exchange OHLCV loading.
- `optimizer`: parameter search over backtest runners.

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
assert result.report.execution_mode == "intent_only"
assert result.report.broker_authority == "backtest_engine"
assert result.report.order_intents[0]["id"] == "L"
assert result.report.final_equity is None
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
```

## License

MIT. See `LICENSE`.

## Installation, Docker, and Publication

```bash
./scripts/install.sh --dev
docker compose run --rm pinelib
```

## Acknowledgements

This project was developed with AI-assisted engineering workflows. The license and release obligations are defined only by `LICENSE` and the repository documentation above.

## Support / Donations

OpenPine development is independent and MIT-licensed. Donations are optional and help keep the public tooling maintained.

- Telegram: https://t.me/OpenPine
- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`

Support does not affect license terms, feature access, or project guarantees.
