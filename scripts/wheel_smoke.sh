#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
rm -rf dist build *.egg-info
"$PYTHON" -m pip wheel --disable-pip-version-check --no-deps --no-build-isolation -w dist .
WHEEL=$(ls dist/pinelib-*.whl | head -n 1)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
INSTALL_DIR="$TMP/site"
mkdir -p "$INSTALL_DIR"
"$PYTHON" -m pip install --disable-pip-version-check --no-index --no-deps --target "$INSTALL_DIR" "$WHEEL" >/dev/null
PYTHONPATH="$INSTALL_DIR" "$PYTHON" - <<'PY'
from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo, run_generated_strategy
import pinelib
assert pinelib.PACKAGE_VERSION == "4.0.0"
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
