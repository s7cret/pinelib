# Stage 4 acceptance limitations

The corrected delivery contains the complete source tree and a functioning local Request Engine candidate, but the full Stage 4 exit gate is intentionally not marked PASS.

## Blocking external inputs

1. The exact OpenPine Contracts 5.0.0rc6 schemas and wheel for `openpine.marketdata.v2` and related request identities were not supplied. The implementation uses strict local frozen views and does not claim schema ownership parity.
2. No exact marketdata-provider RC6 wheel/capability contract was supplied for cross-stack execution.
3. Exact Pine2AST RC6 version packs and Ast2Python request artifacts were not supplied, so the local target catalog is not the authoritative full request denominator.
4. Sealed TradingView HTF/LTF/dynamic/realtime request exports with provenance and hashes are unavailable. Deterministic local reference tests are not called TradingView-verified.
5. Independent semantic/architecture review has not occurred.

## Validation environment limits

The active environment provides Python 3.13.5. Python 3.11 and 3.12 runtime jobs are not available. `ruff`, `black`, and `mypy` are unavailable and are recorded as `NOT_AVAILABLE`, not PASS. The package is built with the local setuptools backend, installed into a clean venv, and checked there.

## Scope boundary

Provider-dependent `request.financial`, `economic`, `earnings`, `dividends`, `splits`, `currency_rate`, `seed`, and `footprint` rows remain explicit fail-closed entries. Stage 5 strategy/BrokerProjection work is not introduced. No broker simulation, data acquisition, renderer, notification delivery, or compiler lowering is implemented in PineLib.
