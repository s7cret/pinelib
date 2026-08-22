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
from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo, run_generated_strategy
import pinelib

assert pinelib.PACKAGE_VERSION == "5.0.0rc3"

class Generated:
    def on_bar(self, runtime, strategy):
        strategy.entry("L", "long", qty=1)

result = run_generated_strategy(
    Generated(),
    PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60")),
    StrategyContext(
        intent_producer_commit="801b908e0ba53d1387cfd032cb6d29aa53ba0ca0",
        intent_strict_production=True,
    ),
    [Bar(0, 1, 1, 1, 1, time_close=3599999)],
)
assert result.report.order_intents
PY
)
echo "pinelib wheel smoke ok"
