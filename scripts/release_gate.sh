#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
run() {
  echo "+ $*"
  "$@"
}
run "$PYTHON" -m compileall -q pinelib tests scripts
run "$PYTHON" -m ruff check .
run env BLACK_NUM_WORKERS="${BLACK_NUM_WORKERS:-1}" "$PYTHON" -m black --check .
run "$PYTHON" -m mypy pinelib
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 run "$PYTHON" -m pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 run "$PYTHON" -m pytest -q -p pytest_cov tests --cov=pinelib --cov-report=term
run "$PYTHON" -m pinelib.quality duplicates pinelib
run "$PYTHON" -m pinelib.quality architecture pinelib --max-lines 700
run "$PYTHON" scripts/run_tv_golden_suite.py
run "$PYTHON" -m pinelib.distribution manifest --root .
run "$PYTHON" -m pinelib.release --root .
run bash scripts/smoke_import_parse.sh
run bash scripts/wheel_smoke.sh
