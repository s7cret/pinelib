# Changelog

## 4.0.0

- Aligned PineLib with the OpenPine 4.x runtime toolchain.
- Added hermetic fallback compatibility for minimal `marketdata_provider` contracts used by tests and offline smoke runs.
- Moved market-data provider integration to an optional extra while keeping conversion helpers compatible with the external package.
- Added release/distribution/quality command modules.
- Added `python -m pinelib` / `pinelib` console entrypoint.
- Added deterministic source archive support and archive hygiene checks.
- Added release gates for ruff, black, mypy, pytest, coverage, duplicate detection, architecture budget, distribution manifest, release manifest, and wheel smoke.
- Fixed `PineArray.shift()` out-of-range fallback import.
- Added `StrategyContext.risk_max_cons_loss_days()` intent recording.
- Fixed batch `ta.change()` / `ta.mom()` sequence handling.
- Fixed batch `ta.correlation()` sequence handling.
- Fixed batch `ta.kcw()` when `ta.kc()` returns vector outputs.
- Fixed batch `ta.sar()` acceleration cap typo.
- Split the TA implementation monolith into focused modules below the architecture budget.
- Fixed `ta.valuewhen()` cache initialization after module split.
- Added batch support for `ta.pivothigh()` / `ta.pivotlow()` and plain sequence support for `ta.rising()` / `ta.falling()`.
- Expanded runtime/TA/parity/reference/IO release-surface test coverage.
- Raised autonomous package coverage gate to 100% line coverage with behavior-driven edge tests.
- Removed optional skipped tests from the default release gate; realtime boundary coverage is now self-contained.
- Hardened wheel smoke to always use offline/no-deps build and install paths.
- Removed residual coverage-exclusion markers from package code while keeping 100% package coverage.

## 2.17.0

- Previous public baseline.
