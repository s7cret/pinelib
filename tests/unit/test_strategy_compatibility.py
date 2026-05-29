from __future__ import annotations

import sys
from typing import cast

import pytest

from pinelib.strategy import (
    BROKER_BOUNDARY_STATUS,
    broker_boundary,
    make_backtest_engine_strategy_adapter,
)


def test_broker_boundary_documents_amended_owner_split() -> None:
    boundary = broker_boundary()

    pinelib_owns = cast(list[str], boundary["pinelib_owns"])
    backtest_engine_owns = cast(list[str], boundary["backtest_engine_owns"])
    claim_boundary = cast(list[str], boundary["claim_boundary"])

    assert boundary["status"] == BROKER_BOUNDARY_STATUS
    assert "strategy order-intent facade" in pinelib_owns
    assert "fill simulation" in backtest_engine_owns
    assert boundary["adapter"] == (
        "backtest_engine.adapters.generated_strategy.make_generated_strategy_adapter"
    )
    assert "no full TradingView parity claim" in claim_boundary


class _GeneratedStrategy:
    pass


def test_backtest_engine_adapter_shim_fails_explicitly_when_package_absent() -> None:
    class _BlockBacktestEngine:
        def find_spec(self, fullname: str, path: object | None = None, target: object | None = None) -> object | None:
            if fullname == "backtest_engine":
                raise ModuleNotFoundError("No module named 'backtest_engine'", name="backtest_engine")
            return None

    sys.meta_path.insert(0, _BlockBacktestEngine())
    sys.modules.pop("backtest_engine", None)
    with pytest.raises(RuntimeError, match="Backtest Engine is a separate package"):
        try:
            make_backtest_engine_strategy_adapter(_GeneratedStrategy)
        finally:
            sys.meta_path.pop(0)
