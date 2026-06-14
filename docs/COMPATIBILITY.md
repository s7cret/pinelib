# Compatibility

PineLib 4.0.0 targets `runtime_contract_v1_4` and generated Python modules from the OpenPine 4.x toolchain.

Supported categories include:

- deterministic bar-by-bar series runtime;
- strategy intent APIs;
- request/provider merge foundations;
- reference containers;
- plot/visual recorders;
- broad TA helper coverage.

Runtime behaviors intentionally outside this package:

- broker/fill/equity authority;
- exchange/network market-data fetching;
- full TradingView realtime infrastructure;
- AST parsing/lowering;
- parameter optimization.

`marketdata-provider` is optional. PineLib includes a small internal compatibility layer so local tests and basic conversion helpers can run without network access.
