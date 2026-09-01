# Stage 3 baseline local support matrix

This table describes the bundled local candidate catalog. It is deliberately not presented as the authoritative Pine v1–v6 denominator.

| Area | Local implementation | Validation boundary |
|---|---|---|
| Generic dispatch prohibition | Direct callables only | Static scan + manifest builder |
| `math.*` and historical aliases | 44 supported rows; `math.random` fail-closed | Generated row tests + edge corpus |
| `str.*` and conversion aliases | 18 supported rows | Golden/hostile formatting tests |
| Inputs | 11 immutable admitted input functions | Schema/value/restart identity tests |
| Calendar/time/session | 9 context functions | UTC, DST, overnight, invalid-zone tests |
| `syminfo`/`timeframe`/`barstate` | 24 context fields | Admitted-context and lifecycle tests |
| TA | 102 rows across namespace/global aliases | Streaming/state/checkpoint/reference tests |
| Arrays | 18 operations | Alias/copy/bounds/sort/search/rollback tests |
| Maps | 10 operations | Order/type/missing-key/copy/checkpoint tests |
| Matrices | 6 operations | Bounds/type/copy/checkpoint tests |
| UDT/enums | 5 rows | Field/copy/identity/equality tests; receiver-method dispatch remains upstream-dependent |
| Visuals | 14 event producers | Identity/limits/rollback/checkpoint tests |
| Alerts | 2 event producers | Identity/limits/rollback/checkpoint tests |

## TA families in the local catalog

- Moving averages: SMA, EMA, RMA, WMA, VWMA, SWMA, ALMA, HMA.
- Momentum: RSI, MACD, MOM, ROC, CMO, TSI, stochastic.
- Volatility/channels: TR, ATR, BB, BBW, KC, KCW, range, WPR.
- Trend/extrema: DMI, supertrend, SAR, pivots, rising/falling, highest/lowest and bar offsets.
- Statistics: variance, stdev, dev, correlation, percentiles, percent rank, linreg, median, mode, valuewhen and barssince.
- Volume: CCI, MFI, OBV, VWAP and cumulative sum.

A supported local row means the callable imports, its signature is captured, and its local behavior suite executes. It does not by itself mean TradingView-oracle verification.
