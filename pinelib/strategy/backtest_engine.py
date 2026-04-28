"""Compatibility shim for the amended Backtest Engine broker boundary.

Historically, some integration docs expected broker/backtest entry points under
``pinelib.strategy``. In the amended 6-package architecture PineLib keeps only
runtime/order-intent compatibility; final broker/fill/equity authority belongs
to the separate ``backtest_engine`` package.

This module gives legacy callers a discoverable migration surface without making
PineLib depend on Backtest Engine at import time.
"""

from __future__ import annotations

from typing import Any, cast

BROKER_BOUNDARY_STATUS = "BACKTEST_ENGINE_AUTHORITY"


def broker_boundary() -> dict[str, object]:
    """Return the explicit amended broker ownership mapping."""

    return {
        "status": BROKER_BOUNDARY_STATUS,
        "pinelib_owns": [
            "PineRuntime lifecycle",
            "series/history semantics",
            "Pine builtins and namespace helpers",
            "strategy order-intent facade",
            "runtime diagnostics",
        ],
        "backtest_engine_owns": [
            "order lifecycle",
            "fill simulation",
            "commission and slippage",
            "position/trade/equity accounting",
            "broker-affecting strategy settings",
            "backtest reports and metrics",
        ],
        "adapter": "backtest_engine.adapters.generated_strategy.make_generated_strategy_adapter",
        "claim_boundary": [
            "no full Pine v6 support claim",
            "no full TradingView parity claim",
            "no 100% compatibility claim",
        ],
    }


def make_backtest_engine_strategy_adapter(
    generated_strategy_class: type[Any],
    *,
    options: object | None = None,
) -> type[Any]:
    """Return a Backtest Engine adapter for an AST2Python/PineLib strategy class.

    Backtest Engine is an optional separate package. Import it lazily so plain
    ``import pinelib`` and ``import pinelib.strategy`` remain dependency-free.
    """

    try:
        from backtest_engine.adapters.generated_strategy import (  # type: ignore[import-not-found]
            make_generated_strategy_adapter,
        )
    except ModuleNotFoundError as exc:
        if exc.name == "backtest_engine":
            raise RuntimeError(
                "Backtest Engine is a separate package in the amended 6-package stack. "
                "Install/import backtest_engine and use "
                "backtest_engine.adapters.generated_strategy.make_generated_strategy_adapter, "
                "or call this shim only in an environment where backtest_engine is available."
            ) from exc
        raise
    if options is None:
        return cast(type[Any], make_generated_strategy_adapter(generated_strategy_class))
    return cast(
        type[Any],
        make_generated_strategy_adapter(generated_strategy_class, options=options),
    )


__all__ = [
    "BROKER_BOUNDARY_STATUS",
    "broker_boundary",
    "make_backtest_engine_strategy_adapter",
]
