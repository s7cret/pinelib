# Security

PineLib does not open network connections or fetch market data by itself. File IO helpers are limited to caller-supplied paths. Optional Parquet support imports pandas only when requested.

Generated code should be treated as executable Python and run in the same sandboxing model as any other generated strategy code. Broker execution, order routing, credentials, and live trading controls must remain outside PineLib.
