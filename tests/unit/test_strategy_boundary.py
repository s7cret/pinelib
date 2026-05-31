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


def test_ta_public_init_is_reexport_boundary() -> None:
    init_path = ROOT / "pinelib" / "ta" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))

    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in tree.body)
    assert init_path.read_text(encoding="utf-8").count("\n") < 120
    for module_name in [
        "moving_average.py",
        "momentum.py",
        "volatility.py",
        "volume.py",
        "statistics.py",
        "trend.py",
        "utils.py",
    ]:
        assert (ROOT / "pinelib" / "ta" / module_name).exists()


def test_strategy_context_keeps_models_in_models_module() -> None:
    context_path = ROOT / "pinelib" / "strategy" / "context.py"
    tree = ast.parse(context_path.read_text(encoding="utf-8"), filename=str(context_path))

    assert (ROOT / "pinelib" / "strategy" / "models.py").exists()
    model_names = {
        "StrategyDeclaration",
        "Order",
        "Fill",
        "Trade",
        "RiskRule",
        "_OpenLot",
        "_StrategyScalarSeries",
    }
    context_classes = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert context_classes.isdisjoint(model_names)


def test_strategy_context_has_no_broker_fill_authority_methods() -> None:
    context_path = ROOT / "pinelib" / "strategy" / "context.py"
    tree = ast.parse(context_path.read_text(encoding="utf-8"), filename=str(context_path))
    method_names = {
        node.name
        for class_node in tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "StrategyContext"
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    forbidden = {
        "_fill_order",
        "_apply_position_fill",
        "_mark_to_market",
        "_update_equity_extremes",
        "_update_lot_excursions",
        "_diagnose_margin_risk",
    }
    assert method_names.isdisjoint(forbidden)
