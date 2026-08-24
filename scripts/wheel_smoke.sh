#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONTRACTS_WHEEL=${OPENPINE_CONTRACTS_WHEEL:-}
if [[ -z "$CONTRACTS_WHEEL" || ! -f "$CONTRACTS_WHEEL" ]]; then
    echo "OPENPINE_CONTRACTS_WHEEL must name the exact local contracts wheel" >&2
    exit 1
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
DIST_DIR="$TMP/dist"
"$PYTHON" -m build --wheel --outdir "$DIST_DIR" "$ROOT"
shopt -s nullglob
wheels=("$DIST_DIR"/pinelib-*.whl)
if (( ${#wheels[@]} != 1 )); then
    printf 'expected exactly one wheel in %s, found %s\n' "$DIST_DIR" "${#wheels[@]}" >&2
    exit 1
fi
VENV="$TMP/venv"
"$PYTHON" -m venv "$VENV"
env -u PYTHONPATH "$VENV/bin/python" -m pip install --disable-pip-version-check \
    "$CONTRACTS_WHEEL" "${wheels[0]}" >/dev/null
(
    cd "$TMP"
    env -u PYTHONPATH "$VENV/bin/python" -I - <<'PY'
from openpine_contracts import seal_content_hash
from pinelib import (
    Bar,
    PineRuntime,
    RuntimeConfig,
    StrategyContext,
    SymbolInfo,
    TimeframeInfo,
    run_generated_strategy,
)
import pinelib

assert pinelib.PACKAGE_VERSION == "5.0.0rc4"

commit = "801b908e0ba53d1387cfd032cb6d29aa53ba0ca0"
hash_a = "sha256:" + ("a" * 64)
hash_b = "sha256:" + ("b" * 64)
hash_c = "sha256:" + ("c" * 64)
hash_d = "sha256:" + ("d" * 64)
components = (
    "openpine-contracts",
    "marketdata-provider",
    "pinelib",
    "pine2ast",
    "ast2python",
    "backtest_engine",
    "optimizer",
    "openpine",
)
context = seal_content_hash(
    {
        "schema_id": "openpine.execution_context.v1",
        "schema_version": "1.0.0",
        "producer": "pinelib-wheel-smoke",
        "producer_version": "5.0.0-rc.4",
        "producer_commit": commit,
        "stack_id": hash_d,
        "created_at_utc_ms": 0,
        "serializer_id": "openpine.canonical.json.v1",
        "content_hash_alg": "sha256",
        "run_id": "wheel-smoke-run",
        "strategy_id": "wheel-smoke-strategy",
        "session_id": "wheel-smoke-session",
        "stack_manifest_hash": hash_d,
        "wheel_identities": [
            {"name": name, "version": "5.0.0rc4", "content_hash": hash_b}
            for name in components
        ],
        "schema_hashes": {
            "openpine.execution_context.v1": hash_a,
            "openpine.worker.protocol.v2": hash_b,
            "openpine.checkpoint.v1": hash_c,
            "openpine.checkpoint.proof.v1": hash_d,
            "openpine.intent.v2": hash_b,
        },
        "generated_artifact_hash": hash_b,
        "source_hash": hash_c,
        "emitted_module_hash": hash_d,
        "data_snapshot_hash": hash_a,
        "series_id": "TEST:AAA:60",
        "instrument_id": "TEST:AAA",
        "exchange": "TEST",
        "market": "stock",
        "symbol": "AAA",
        "timeframe": "60",
        "timezone": "UTC",
        "currency": "USD",
        "mintick": "0.01",
        "pointvalue": "1",
        "session_policy": "24x7",
        "semantic_profile": "strict_5x",
        "finality_policy": "CLOSED_BAR_ONLY",
        "warmup_policy": "CALC_ONLY",
        "score_policy": "ALL_BARS",
        "end_policy": "LIQUIDATE_ON_LAST_BAR",
        "capabilities": ["closed_bar", "deterministic_clock"],
        "producer_commits": {name: commit for name in components},
        "policy_registry_version": "openpine.policies.rc4.v1",
        "schema_registry_version": "openpine.schemas.rc4.v1",
        "capability_registry_version": "openpine.capabilities.rc4.v1",
    },
    schema_id="openpine.execution_context.v1",
)

class Generated:
    def on_bar(self, runtime, strategy):
        strategy.entry("L", "long", qty=1)

result = run_generated_strategy(
    Generated(),
    PineRuntime(
        SymbolInfo(
            "TEST:AAA",
            timezone="UTC",
            session="24x7",
            mintick=0.01,
            exchange="TEST",
            type="stock",
            currency="USD",
            pointvalue=1.0,
        ),
        TimeframeInfo.from_string("60"),
        config=RuntimeConfig(semantic_profile="strict_5x"),
    ),
    StrategyContext(
        intent_producer_commit=commit,
        intent_strict_production=True,
        intent_execution_context=context,
    ),
    [Bar(0, 1, 1, 1, 1, time_close=3599999)],
)
assert result.report.order_intents
PY
)
echo "pinelib wheel smoke ok"
