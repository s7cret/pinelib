from __future__ import annotations

import pytest

from pinelib.strategy import (
    BROKER_BOUNDARY_STATUS,
    broker_boundary,
    make_backtest_engine_strategy_adapter,
)


def test_broker_boundary_documents_amended_owner_split() -> None:
    boundary = broker_boundary()

    assert boundary["status"] == BROKER_BOUNDARY_STATUS
    assert "strategy order-intent facade" in boundary["pinelib_owns"]
    assert "fill simulation" in boundary["backtest_engine_owns"]
    assert boundary["adapter"] == (
        "backtest_engine.adapters.generated_strategy.make_generated_strategy_adapter"
    )
    assert "no full TradingView parity claim" in boundary["claim_boundary"]


class _GeneratedStrategy:
    pass


def test_backtest_engine_adapter_shim_fails_explicitly_when_package_absent() -> None:
    with pytest.raises(RuntimeError, match="Backtest Engine is a separate package"):
        make_backtest_engine_strategy_adapter(_GeneratedStrategy)
