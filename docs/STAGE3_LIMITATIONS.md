# Stage 3 acceptance limitations (historical baseline)

The implementation is reviewable and packaged, but the full Stage 3 exit gate is intentionally not marked PASS.

## Blocking external inputs

1. The Stage 2 packet does not contain the exact OpenPine Contracts RC6 schemas for the target manifest and related inter-package identities.
2. The exact Pine2AST RC6 version packs / callable-overload denominator are absent, so the local 264-row catalog cannot be represented as the authoritative full v1–v6 catalog.
3. Sealed TradingView oracle outputs with source, retrieval metadata and hashes are not present. Local slow/reference tests are not mislabeled as TradingView evidence.
4. Independent semantic/architecture review has not occurred.

## Validation environment limits

The active environment provides Python 3.13.5. Python 3.11 and 3.12 runtime jobs are not executed here. `ruff`, `black`, `mypy`, `build`, and `twine` are unavailable and cannot be installed without package-index access; compile, AST/static scans, tests, coverage and setuptools build backend checks are recorded instead. These substitutions do not convert the unavailable quality gates into PASS.

## Scope limitations

- `math.random` is explicitly unsupported and fail-closed because a deterministic admitted random-stream contract is not available.
- UDT/enum storage and copying are implemented, while compiler-described receiver method binding still requires exact generated artifact type metadata.
- Request contexts, dynamic requests, HTF/LTF alignment, and provider integration were excluded from the Stage 3 candidate; they are implemented locally in the current Stage 4 tree and documented separately.
- Strategy intents and `BrokerProjection` belong to Stage 5 and are not reintroduced into this Stage 3 source.
