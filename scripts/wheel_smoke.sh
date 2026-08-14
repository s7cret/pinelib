#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
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
WHEEL="${wheels[0]}"
INSTALL_DIR="$TMP/site"
mkdir -p "$INSTALL_DIR"
"$PYTHON" -m pip install --disable-pip-version-check --no-index --no-deps --target "$INSTALL_DIR" "$WHEEL" >/dev/null
PYTHONPATH="$INSTALL_DIR" "$PYTHON" - <<'PY'
from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo, run_generated_strategy
import pinelib
assert pinelib.PACKAGE_VERSION == "4.0.2"
class Generated:
    def on_bar(self, runtime, strategy):
        strategy.entry("L", "long", qty=1)
result = run_generated_strategy(
    Generated(),
    PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60")),
    StrategyContext(),
    [Bar(0, 1, 1, 1, 1, time_close=3599999)],
)
assert result.report.order_intents
PY
echo "pinelib wheel smoke ok"
