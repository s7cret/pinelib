from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pinelib_strategy_api_has_no_backtest_engine_compatibility_shim() -> None:
    import pinelib.strategy as strategy

    assert not (ROOT / "pinelib" / "strategy" / "backtest_engine.py").exists()
    assert "make_backtest_engine_strategy_adapter" not in strategy.__all__
    assert "broker_boundary" not in strategy.__all__


def test_pinelib_production_does_not_import_backtest_engine() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "pinelib").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "backtest_engine" or alias.name.startswith("backtest_engine."):
                        offenders.append(path.relative_to(ROOT).as_posix())
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "backtest_engine" or module.startswith("backtest_engine."):
                    offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
