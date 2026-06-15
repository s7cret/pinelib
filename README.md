# PineLib 4.0.0

> Deterministic Python runtime foundation for AST2Python-generated Pine-compatible modules.

[![Version](https://img.shields.io/badge/version-4.0.0-blue)](https://github.com/s7cret/pinelib) [![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue)](https://github.com/s7cret/pinelib) [![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/s7cret/pinelib)


**GitHub description:** PineLib provides Pine-style series, bar lifecycle, inputs, request helpers, strategy intent APIs, TA helpers, visual recorders, and runtime primitives for generated OpenPine modules.

**Suggested topics:** `pine-script`, `runtime`, `technical-analysis`, `tradingview`, `backtesting`, `algorithmic-trading`, `python`, `openpine`.

## What PineLib is

PineLib is the runtime surface that generated Python modules target. AST2Python emits code that calls PineLib primitives for series/history behavior, bar lifecycle state, inputs, technical-analysis helpers, strategy intent recording, visual recorders, request foundations, and reference containers.

```text
pine2ast -> ast2python -> generated Python -> pinelib -> backtest-engine / openpine
```

PineLib intentionally records strategy intent. The final broker, fill, trade, equity, and report authority belongs to Backtest Engine and OpenPine.

## Supported runtime surface

- `Series[T]` history with current/committed bar semantics.
- `PineRuntime` bar-loop metadata, OHLCV series, `barstate`, inputs, diagnostics, and commit lifecycle.
- `StrategyContext` intent APIs for `strategy.entry`, `strategy.order`, `strategy.exit`, `strategy.close`, cancel calls, and risk-rule recording.
- `run_generated_strategy()` for intent-only bar-by-bar execution of generated modules.
- `request.security` and lower-timeframe foundations with explicit data-provider protocols and diagnostics.
- Pine reference containers: `PineArray`, `PineMap`, and `PineMatrix`.
- Visual object lifecycle recorder and `PlotRecorder` for debug/export paths.
- TA helpers for moving averages, momentum, volatility, trend, statistics, and volume.
- TradingView fixture/oracle helpers for parity evidence.
- Optional market-data contract compatibility without making `marketdata-provider` mandatory.

## Boundaries

PineLib does not parse Pine source, lower AST to Python, fetch exchange data, optimize parameters, or act as the final broker/fill/equity ledger. It also does not claim complete TradingView runtime parity. It provides deterministic runtime primitives for the generated-code layer.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Install from GitHub tag:

```bash
python -m pip install 'git+https://github.com/s7cret/pinelib.git@v4.0.0'
```

Optional market-data integration:

```bash
python -m pip install -e '.[marketdata]'
```

## Basic generated-strategy runner

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
print(result.report.execution_mode)
print(result.report.broker_authority)
```

## Bar file IO

```python
from pinelib import load_bars, load_bars_csv

bars = load_bars_csv("bars.csv")      # required columns: time, open, high, low, close
bars2 = load_bars("bars.parquet")     # optional pandas/parquet engine
```

## Notes for AST2Python integrations

Generated modules should target public imports exposed through `pinelib.__all__`. Plot and visual output should remain policy-controlled by the generator/runtime (`drop`, `record`, or `error`), while PineLib provides deterministic recorders for the selected policy.

## Repository layout

```text
pinelib/
  core/                   series, runtime state, bar lifecycle, primitive helpers
  strategy/               strategy intent context and risk-rule helpers
  ta/                     technical-analysis functions
  request/                security/request foundations and provider protocols
  collections/            PineArray, PineMap, PineMatrix
  visuals/                plot and object recorders
  backtest/               generated-strategy runner and report helpers
  io/                     bar loading utilities
  tests/                  runtime, fixture, contract, and golden checks
```

## Release checks

```bash
bash scripts/release_gate.sh
```

Expanded local gate:

```bash
python -m compileall -q pinelib tests scripts
python -m ruff check .
BLACK_NUM_WORKERS=1 python -m black --check .
python -m mypy pinelib
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p pytest_cov tests --cov=pinelib --cov-report=term
python -m pinelib.quality duplicates pinelib
python -m pinelib.quality architecture pinelib --max-lines 700
python scripts/run_tv_golden_suite.py
python -m pinelib.distribution manifest --root .
python -m pinelib.release --root .
bash scripts/smoke_import_parse.sh
bash scripts/wheel_smoke.sh
```

## Documentation

- `docs/ARCHITECTURE.md` — runtime architecture and module boundary.
- `docs/COMPATIBILITY.md` — runtime compatibility and non-goals.
- `docs/DEVELOPMENT.md` — local setup and checks.
- `docs/RELEASE_4_0.md` — 4.0.0 release checklist.
- `docs/SECURITY.md` — runtime safety and integration guidance.

## License

MIT. See `LICENSE`.

## Support

OpenPine development is independent and MIT-licensed. Support is optional and does not change license terms, feature access, or project guarantees.

- Telegram: https://t.me/OpenPine
- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`