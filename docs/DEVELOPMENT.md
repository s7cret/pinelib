# Development

Use the same local gate that CI and release checks use. The package is intentionally dependency-light; tests run without network access and the wheel smoke installs the built wheel with `--no-deps`.

```bash
bash scripts/release_gate.sh
```

Expanded gate:

```bash
python -m compileall -q pinelib tests scripts
python -m ruff check .
BLACK_NUM_WORKERS=1 python -m black --check .
python -m mypy pinelib
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p pytest_cov tests --cov=pinelib --cov-report=term
python -m pinelib.quality duplicates pinelib
python -m pinelib.quality architecture pinelib --max-lines 700
python scripts/run_tv_golden_suite.py
python -m pinelib.distribution manifest --root .
python -m pinelib.release --root .
bash scripts/smoke_import_parse.sh
bash scripts/wheel_smoke.sh
```

Release thresholds:

- 100% package line coverage for `pinelib`.
- No duplicate Python implementation groups.
- No Python module above 700 lines.
- `ruff`, `black --check`, and `mypy pinelib` must pass.
- Wheel smoke must work offline via `pip wheel --no-deps --no-build-isolation` and `pip install --no-index --no-deps --target`.

Optional cross-repo checks that require sibling repositories belong outside this package gate and should run in the full OpenPine workspace.
