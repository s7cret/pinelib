from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Direction = Literal["long", "short"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
OrderKind = Literal["entry", "order", "exit", "close"]
OrderStatus = Literal["pending", "filled", "cancelled"]


@dataclass(slots=True)
class StrategyDeclaration:
    initial_capital: float = 100000.0
    currency: str = "USD"
    default_qty_type: str = "fixed"
    default_qty_value: float = 1.0
    pyramiding: int = 1
    commission_type: str = "percent"
    commission_value: float = 0.0
    slippage: float = 0.0
    process_orders_on_close: bool = False
    calc_on_order_fills: bool = False
    calc_on_every_tick: bool = False
    use_bar_magnifier: bool = False
    backtest_fill_limits_assumption: float | int | None = None
    close_entries_rule: str = "FIFO"
    margin_long: float = 100.0
    margin_short: float = 100.0
    fill_orders_on_standard_ohlc: bool | None = None
    risk_free_rate: float = 0.0
    max_bars_back: int | None = None
    max_lines_count: int | None = None
    max_labels_count: int | None = None
    max_boxes_count: int | None = None
    strict_tv_parity: bool = False
    qty_step: float | None = None
    qty_rounding_mode: str = "none"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Order:
    id: str
    direction: Direction | None
    qty: float | None
    qty_percent: float | None = None
    type: OrderType = "market"
    kind: OrderKind = "order"
    limit: float | None = None
    stop: float | None = None
    profit: float | None = None
    loss: float | None = None
    from_entry: str | None = None
    parent_exit_id: str | None = None
    bracket_group: str | None = None
    oca_name: str | None = None
    oca_type: str | None = None
    created_bar_index: int = -1
    created_time: int | None = None
    status: OrderStatus = "pending"
    filled_qty: float = 0.0
    fill_price: float | None = None
    fill_source: str | None = None
    source_map: object | None = None
    comment: str | None = None
    comment_profit: str | None = None
    comment_loss: str | None = None
    comment_trailing: str | None = None
    alert_message: str | None = None
    alert_profit: str | None = None
    alert_loss: str | None = None
    alert_trailing: str | None = None
    disable_alert: bool | None = None
    immediate: bool = False
    default_qty_price: float | None = None
    default_qty_equity: float | None = None
    trail_activation: float | None = None
    trail_offset: float | None = None
    trail_stop: float | None = None
    trail_active: bool = False


@dataclass(slots=True)
class Fill:
    order_id: str
    direction: Direction
    qty: float
    price: float
    commission: float
    bar_index: int
    time: int
    kind: OrderKind
    fill_source: str = "ohlc_path"


@dataclass(slots=True)
class Trade:
    entry_id: str
    direction: Direction
    entry_time: int
    entry_bar_index: int
    entry_price: float
    exit_time: int | None
    exit_bar_index: int | None
    exit_price: float | None
    qty: float
    commission: float
    profit: float
    profit_percent: float
    exit_reason: str | None
    fill_source: str | None = None
    max_runup: float | None = None
    max_drawdown: float | None = None
    commission_entry: float | None = None
    commission_exit: float | None = None


@dataclass(frozen=True, slots=True)
class RiskRule:
    name: str
    value: float | None = None
    value_type: str | None = None
    direction: str | None = None


class StrategyLedgerView(Protocol):
    def closedtrades_max_runup(self, index: int) -> float: ...

    def closedtrades_max_drawdown(self, index: int) -> float: ...

    def opentrades_max_runup(self, index: int) -> float: ...

    def opentrades_max_drawdown(self, index: int) -> float: ...


@dataclass(slots=True)
class _OpenLot:
    entry_id: str
    direction: Direction
    qty: float
    entry_price: float
    entry_time: int
    entry_bar_index: int
    commission: float = 0.0
    mfe_per_unit: float = 0.0
    mae_per_unit: float = 0.0


class _StrategyScalarSeries:
    def __init__(self, value: int | float = 0) -> None:
        self._current: int | float = value
        self._history: list[int | float] = []

    @property
    def current(self) -> int | float:
        return self._current

    @property
    def committed_length(self) -> int:
        return len(self._history)

    def set_current(self, value: int | float) -> None:
        self._current = value

    def commit_current(self) -> None:
        self._history.append(self._current)

    def __getitem__(self, offset: int) -> int | float:
        if offset < 0:
            raise IndexError("negative history offsets are not supported")
        if offset == 0:
            return self._current
        if offset <= len(self._history):
            return self._history[-offset]
        return 0

    def __float__(self) -> float:
        return float(self._current)

    def __int__(self) -> int:
        return int(self._current)

    def __bool__(self) -> bool:
        return bool(self._current)

    def __add__(self, other: Any) -> Any:
        return self._current + _unwrap_strategy_scalar(other)

    def __radd__(self, other: Any) -> Any:
        return _unwrap_strategy_scalar(other) + self._current

    def __sub__(self, other: Any) -> Any:
        return self._current - _unwrap_strategy_scalar(other)

    def __rsub__(self, other: Any) -> Any:
        return _unwrap_strategy_scalar(other) - self._current

    def __mul__(self, other: Any) -> Any:
        return self._current * _unwrap_strategy_scalar(other)

    def __rmul__(self, other: Any) -> Any:
        return _unwrap_strategy_scalar(other) * self._current

    def __truediv__(self, other: Any) -> Any:
        return self._current / _unwrap_strategy_scalar(other)

    def __rtruediv__(self, other: Any) -> Any:
        return _unwrap_strategy_scalar(other) / self._current

    def __eq__(self, other: object) -> bool:
        return self._current == _unwrap_strategy_scalar(other)

    def __lt__(self, other: Any) -> bool:
        return self._current < _unwrap_strategy_scalar(other)

    def __le__(self, other: Any) -> bool:
        return self._current <= _unwrap_strategy_scalar(other)

    def __gt__(self, other: Any) -> bool:
        return self._current > _unwrap_strategy_scalar(other)

    def __ge__(self, other: Any) -> bool:
        return self._current >= _unwrap_strategy_scalar(other)


def _unwrap_strategy_scalar(value: Any) -> Any:
    return getattr(value, "_current", value)
