# PineLib Runtime v0.1.0

PineLib v0.1.0 is the first production-quality runtime foundation for executing
AST2Python-generated Pine-compatible code against the v1.4 runtime contract.

Implemented in this milestone:

- contract/version metadata for `pinelib` and runtime contract `1.4`
- validated `Bar` model with UTC millisecond timestamps
- `Series[T]` with Pine-compatible current vs committed history semantics
- `PineRuntime` core loop with built-in bar series registration and commit ownership
- `na`, `nz`, `fixnan`, inclusive `pine_range`, and basic Pine numeric helpers
- `DataProvider` protocols and in-memory validated provider
- timezone/session-aware `time()` and `time_close()` scaffold using `zoneinfo`
- pytest, ruff, black, mypy, compileall, release manifest, and reproducible archive

## Install

```bash
pip install -e .[dev]
```

## Minimal runtime loop

```python
from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo
from pinelib.request import InMemoryDataProvider

bars = [
    Bar(time=1704067200000, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0),
]

provider = InMemoryDataProvider({("TEST:AAA", "60"): bars})
runtime = PineRuntime(
    symbol_info=SymbolInfo(tickerid="TEST:AAA", timezone="UTC", session="0000-2359:1234567"),
    timeframe=TimeframeInfo.from_string("60"),
    data_provider=provider,
    config=RuntimeConfig(),
)

for bar in provider.get_bars("TEST:AAA", "60", None, None):
    runtime.begin_bar(bar)
    close_series = runtime.series("my_close_copy", "float")
    close_series.set_current(runtime.close[0])
    runtime.end_bar()
```

## Coverage map for v0.1

- Core runtime: implemented
- Request/data access foundation: implemented without `request.security` execution
- Sessions/time helpers: implemented scaffold and contract tests
- TA namespace, broker emulator, inputs, visuals: deferred beyond v0.1

Unsupported future features are not silently emulated; the runtime raises typed,
diagnostic-bearing errors where parity would otherwise be misleading.

