# Architecture

PineLib is the runtime layer for Python code generated from Pine ASTs. The package is intentionally split by runtime concern:

- `pinelib.core` — bars, series, runtime, inputs, types, operators, time/session helpers.
- `pinelib.request` — provider protocols and `request.security` merge/runtime helpers.
- `pinelib.strategy` — strategy declarations, order/risk intent recording, broker-ledger views.
- `pinelib.ta` — technical-analysis helpers used by generated code.
- `pinelib.reference` — array/map/matrix reference containers.
- `pinelib.plot` and `pinelib.visual` — deterministic recorders, not renderers.
- `pinelib.parity` — TradingView fixture comparison helpers.

The package does not parse Pine, generate Python, fetch exchange data, or own broker fills/equity. Those responsibilities belong to sibling OpenPine components.
