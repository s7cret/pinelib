# PineLib Runtime v0.4.0

PineLib is a Python runtime foundation for AST2Python-generated Pine-compatible code.
v0.4.0 advances the v1.4 runtime contract with the first real strategy context and broker-emulator MVP.

Implemented through v0.4.0:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration, commit ownership, and recalculation guard scaffold
- runtime metadata models: `syminfo`, enriched `timeframe`, and `barstate`
- `RuntimeConfig.diagnostics` collection for explicit runtime diagnostics
- `input.int/float/bool/string/timeframe/symbol/session/source` metadata and validation
- `na`, `nz`, `fixnan`, inclusive `pine_range`, and Pine numeric/operator helpers
- `DataProvider` protocols and in-memory provider with normalization metadata log
- timezone/session-aware `time()` and `time_close()` using IANA `zoneinfo`, including DST/overnight coverage
- `request.security` foundation with explicit nested-request diagnostics
- stateful and batch P0 TA helpers: SMA/EMA/RMA/TR/ATR/RSI/MACD/highest/lowest/change/cross helpers
- `StrategyContext` with declaration settings storage for contract P0/P1 fields
- broker emulator MVP:
  - `strategy.entry/order/exit/close/close_all/cancel/cancel_all`
  - market, limit, stop, and stop-limit order models
  - historical next-bar market fills and `process_orders_on_close`
  - TradingView-style synthetic OHLC path (`open→high→low→close` or `open→low→high→close`)
  - gap-at-open price-order fills
  - default sizing: fixed, cash, percent_of_equity
  - commission: percent, cash_per_order, cash_per_contract
  - slippage price adjustment
  - position size/average price/equity/openprofit/netprofit and trade logs
  - entry reversal and pyramiding basics
  - `strategy.exit` bracket OCA cancellation plus reduce/reservation diagnostics (`PL_WARNING_EXIT_QTY_REDUCED`)
  - `calc_on_order_fills` pending-recalc flag and max recalculation guard scaffold

Unsupported parity-affecting strategy settings are diagnosed explicitly; strict TV parity mode raises instead of silently emulating.

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
```

## Coverage map for v0.4

- Core runtime, inputs, request/security, sessions/time helpers, and P0 TA base: implemented foundation
- Strategy broker emulator: MVP implemented for required v0.4 scope
- Deferred: full Bar Magnifier execution, trailing exits, advanced margin/leverage, all TradingView edge cases, visuals, full TA namespace, and golden TradingView parity suite
