from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pinelib.core.bar import Bar
from pinelib.core.runtime import PineRuntime
from pinelib.errors import PL_MISSING_INTRABAR_DATA, PL_UNSUPPORTED_STRATEGY_SETTING, PL_WARNING_BAR_MAGNIFIER_FALLBACK, PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK, PL_WARNING_EXIT_QTY_REDUCED, PineStrategyError

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
    risk_free_rate: float = 0.0
    max_bars_back: int | None = None
    max_lines_count: int | None = None
    max_labels_count: int | None = None
    max_boxes_count: int | None = None
    strict_tv_parity: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Order:
    id: str
    direction: Direction
    qty: float | None
    type: OrderType = "market"
    kind: OrderKind = "order"
    limit: float | None = None
    stop: float | None = None
    from_entry: str | None = None
    parent_exit_id: str | None = None
    oca_name: str | None = None
    oca_type: str | None = None
    created_bar_index: int = -1
    created_time: int | None = None
    status: OrderStatus = "pending"
    filled_qty: float = 0.0
    fill_price: float | None = None
    fill_source: str | None = None
    source_map: object | None = None
    immediate: bool = False


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


@dataclass(slots=True)
class _OpenLot:
    entry_id: str
    direction: Direction
    qty: float
    entry_price: float
    entry_time: int
    entry_bar_index: int
    commission: float = 0.0


class StrategyContext:
    def __init__(self, **kwargs: Any) -> None:
        self.declaration = StrategyDeclaration(**kwargs)
        self.initial_capital = float(self.declaration.initial_capital)
        self.currency = self.declaration.currency
        self.default_qty_type = self.declaration.default_qty_type
        self.default_qty_value = float(self.declaration.default_qty_value)
        self.pyramiding = int(self.declaration.pyramiding)
        self.commission_type = self.declaration.commission_type
        self.commission_value = float(self.declaration.commission_value)
        self.slippage = float(self.declaration.slippage)
        self.process_orders_on_close = bool(self.declaration.process_orders_on_close)
        self.calc_on_order_fills = bool(self.declaration.calc_on_order_fills)
        self.calc_on_every_tick = bool(self.declaration.calc_on_every_tick)
        self.use_bar_magnifier = bool(self.declaration.use_bar_magnifier)
        self.backtest_fill_limits_assumption = self.declaration.backtest_fill_limits_assumption
        self.close_entries_rule = self.declaration.close_entries_rule
        self.margin_long = self.declaration.margin_long
        self.margin_short = self.declaration.margin_short
        self.max_bars_back = self.declaration.max_bars_back
        self.equity = self.initial_capital
        self.netprofit = 0.0
        self.openprofit = 0.0
        self.grossprofit = 0.0
        self.grossloss = 0.0
        self.position_size = 0.0
        self.position_avg_price = 0.0
        self.position_entry_name: str | None = None
        self.opentrades = 0
        self.closedtrades = 0
        self.wintrades = 0
        self.losstrades = 0
        self.eventrades = 0
        self.max_drawdown = 0.0
        self.max_runup = 0.0
        self.pending_orders: list[Order] = []
        self.fills: list[Fill] = []
        self.closed_trade_log: list[Trade] = []
        self.open_trade_log: list[Trade] = []
        self._lots: list[_OpenLot] = []
        self._fill_recalc_pending = False
        self._calc_every_tick_warned = False
        self._diagnostics_target: object | None = None
        self._runtime: PineRuntime | None = None

    def attach_runtime(self, runtime: PineRuntime) -> None:
        runtime.strategy = self
        self._runtime = runtime
        self._diagnostics_target = runtime.config
        self._validate_settings(runtime)

    def _validate_settings(self, runtime: PineRuntime) -> None:
        unsupported: list[str] = []
        if self.calc_on_every_tick:
            self._emit(runtime, PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK, "calc_on_every_tick needs realtime/tick data; historical MVP uses close pass")
        if self.backtest_fill_limits_assumption not in (None, 0):
            unsupported.append("backtest_fill_limits_assumption")
        if self.close_entries_rule not in ("FIFO", "ANY"):
            unsupported.append("close_entries_rule")
        if unsupported:
            msg = "Unsupported strategy settings: " + ", ".join(unsupported)
            if self.declaration.strict_tv_parity or runtime.config.strict_tv_parity:
                raise PineStrategyError(msg, code=PL_UNSUPPORTED_STRATEGY_SETTING)
            self._emit(runtime, PL_UNSUPPORTED_STRATEGY_SETTING, msg, settings=unsupported)

    def entry(self, id: str, direction: Direction, qty: float | None = None, limit: float | None = None, stop: float | None = None, *, source_map: object | None = None) -> None:
        self._add_order(id, direction, qty, limit, stop, "entry", source_map=source_map)

    def order(self, id: str, direction: Direction, qty: float | None = None, limit: float | None = None, stop: float | None = None, oca_name: str | None = None, oca_type: str | None = None, *, source_map: object | None = None) -> None:
        order = self._make_order(id, direction, qty, limit, stop, "order", source_map)
        order.oca_name = oca_name
        order.oca_type = oca_type
        self.pending_orders.append(order)

    def exit(self, id: str, from_entry: str | None = None, qty: float | None = None, qty_percent: float | None = None, limit: float | None = None, stop: float | None = None, profit: float | None = None, loss: float | None = None, trail_price: float | None = None, trail_points: float | None = None, trail_offset: float | None = None, *, source_map: object | None = None) -> None:
        if trail_price is not None or trail_points is not None or trail_offset is not None:
            self._emit(None, PL_UNSUPPORTED_STRATEGY_SETTING, "Trailing exits are not implemented in v0.4.0", order_id=id)
            return
        if limit is None and profit is not None and self.position_avg_price:
            limit = self.position_avg_price + (profit if self.position_size >= 0 else -profit)
        if stop is None and loss is not None and self.position_avg_price:
            stop = self.position_avg_price - (loss if self.position_size >= 0 else -loss)
        available = abs(self._available_exit_qty(from_entry))
        requested = self._resolve_exit_qty(qty, qty_percent, available)
        reserved = sum(o.qty or 0.0 for o in self.pending_orders if o.kind == "exit" and o.status == "pending" and o.from_entry == from_entry)
        actual = max(0.0, min(requested, max(0.0, available - reserved)))
        if actual < requested or (qty_percent is not None and qty_percent > 100):
            self._emit(None, PL_WARNING_EXIT_QTY_REDUCED, "strategy.exit quantity reduced to available unreserved position", order_id=id, requested=requested, actual=actual)
        if actual <= 0:
            return
        direction: Direction = "short" if self.position_size > 0 else "long"
        group = f"exit:{id}:{from_entry or '*'}"
        created_bar_index, created_time = self._created_order_location()
        if limit is not None:
            self.pending_orders.append(Order(f"{id}:limit", direction, actual, "limit", "exit", limit=limit, from_entry=from_entry, parent_exit_id=id, oca_name=group, oca_type="reduce", created_bar_index=created_bar_index, created_time=created_time, source_map=source_map))
        if stop is not None:
            self.pending_orders.append(Order(f"{id}:stop", direction, actual, "stop", "exit", stop=stop, from_entry=from_entry, parent_exit_id=id, oca_name=group, oca_type="reduce", created_bar_index=created_bar_index, created_time=created_time, source_map=source_map))
        if limit is None and stop is None:
            self.pending_orders.append(Order(id, direction, actual, "market", "exit", from_entry=from_entry, parent_exit_id=id, oca_name=group, oca_type="reduce", created_bar_index=created_bar_index, created_time=created_time, source_map=source_map))

    def close(self, id: str, qty: float | None = None, qty_percent: float | None = None, immediately: bool = False, *, source_map: object | None = None) -> None:
        available = abs(sum(l.qty for l in self._lots if l.entry_id == id))
        if available <= 0:
            return
        close_qty = self._resolve_exit_qty(qty, qty_percent, available)
        direction: Direction = "short" if self.position_size > 0 else "long"
        created_bar_index, created_time = self._created_order_location()
        self.pending_orders.append(Order(f"close:{id}", direction, min(close_qty, available), "market", "close", from_entry=id, created_bar_index=created_bar_index, created_time=created_time, source_map=source_map, immediate=immediately))

    def close_all(self, immediately: bool = False, *, source_map: object | None = None) -> None:
        if self.position_size == 0:
            return
        direction: Direction = "short" if self.position_size > 0 else "long"
        created_bar_index, created_time = self._created_order_location()
        self.pending_orders.append(Order("close_all", direction, abs(self.position_size), "market", "close", created_bar_index=created_bar_index, created_time=created_time, source_map=source_map, immediate=immediately))

    def cancel(self, id: str, *, source_map: object | None = None) -> None:
        del source_map
        for order in self.pending_orders:
            if order.id == id or order.parent_exit_id == id:
                order.status = "cancelled"

    def cancel_all(self, *, source_map: object | None = None) -> None:
        del source_map
        for order in self.pending_orders:
            order.status = "cancelled"

    def accept_orders_from_generated_code(self) -> None:
        return None

    def has_fill_recalc_pending(self) -> bool:
        return self._fill_recalc_pending

    def update_position_equity_trades_after_fill(self) -> None:
        self._fill_recalc_pending = False

    def process_orders_for_bar(self, *, runtime: PineRuntime, bar: Bar, recalc_phase: bool = False, intrabar_bars: list[Bar] | None = None) -> None:
        self.attach_runtime(runtime) if runtime.strategy is not self else None
        path, fill_source = self._execution_path(runtime, bar, intrabar_bars)
        fills_before = len(self.fills)
        while True:
            candidates: list[tuple[int, int, Order, float]] = []
            for order_index, order in enumerate(list(self.pending_orders)):
                if order.status != "pending":
                    continue
                if not self._eligible(order, runtime.bar_index + 1, recalc_phase):
                    continue
                event = self._find_fill_event(order, path, bar)
                if event is None:
                    continue
                step_index, fill_price = event
                candidates.append((step_index, order_index, order, fill_price))
            if not candidates:
                break
            _, _, order, fill_price = min(candidates, key=lambda item: (item[0], item[1]))
            if order.status != "pending":
                continue
            self._fill_order(order, fill_price, runtime, bar, fill_source)
        self.pending_orders = [o for o in self.pending_orders if o.status == "pending"]
        self._mark_to_market(bar.close)
        if len(self.fills) > fills_before and self.calc_on_order_fills:
            self._fill_recalc_pending = True

    @staticmethod
    def ohlc_path(bar: Bar) -> list[float]:
        if abs(bar.open - bar.high) < abs(bar.open - bar.low):
            return [bar.open, bar.high, bar.low, bar.close]
        return [bar.open, bar.low, bar.high, bar.close]

    def _add_order(self, id: str, direction: Direction, qty: float | None, limit: float | None, stop: float | None, kind: OrderKind, *, source_map: object | None) -> None:
        self.pending_orders.append(self._make_order(id, direction, qty, limit, stop, kind, source_map))

    def _make_order(self, id: str, direction: Direction, qty: float | None, limit: float | None, stop: float | None, kind: OrderKind, source_map: object | None) -> Order:
        typ: OrderType = "market"
        if limit is not None and stop is not None:
            typ = "stop_limit"
        elif limit is not None:
            typ = "limit"
        elif stop is not None:
            typ = "stop"
        created_bar_index, created_time = self._created_order_location()
        return Order(id=id, direction=direction, qty=qty, type=typ, kind=kind, limit=limit, stop=stop, created_bar_index=created_bar_index, created_time=created_time, source_map=source_map)

    def _created_order_location(self) -> tuple[int, int | None]:
        if self._runtime is not None and self._runtime.current_bar is not None:
            index = self._runtime.bar_index if self._runtime.barstate.isconfirmed else self._runtime.bar_index + 1
            return index, self._runtime.current_bar.time
        if self._runtime is not None:
            return self._runtime.bar_index, None
        return -1, None

    def _eligible(self, order: Order, current_bar_index: int, recalc_phase: bool) -> bool:
        if order.immediate or recalc_phase:
            return True
        if order.created_bar_index < 0:
            order.created_bar_index = current_bar_index
            return self.process_orders_on_close
        return order.created_bar_index < current_bar_index or self.process_orders_on_close

    def _find_fill_price(self, order: Order, path: list[float], bar: Bar) -> float | None:
        event = self._find_fill_event(order, path, bar)
        return None if event is None else event[1]

    def _find_fill_event(self, order: Order, path: list[float], bar: Bar) -> tuple[int, float] | None:
        if order.type == "market":
            current_index = (self._runtime.bar_index + 1) if self._runtime is not None else order.created_bar_index
            return (len(path) - 1, bar.close) if self.process_orders_on_close and order.created_bar_index == current_index else (0, path[0])
        level = order.limit if order.type == "limit" else order.stop
        if order.type == "stop_limit":
            stop_hit = self._crossed_event(path, order.stop, order.direction, is_stop=True)
            if stop_hit is None:
                return None
            level = order.limit
        if level is None:
            return None
        is_stop = order.type == "stop"
        return self._crossed_event(path, level, order.direction, is_stop=is_stop)

    def _crossed(self, path: list[float], level: float | None, direction: Direction, *, is_stop: bool) -> float | None:
        event = self._crossed_event(path, level, direction, is_stop=is_stop)
        return None if event is None else event[1]

    def _crossed_event(self, path: list[float], level: float | None, direction: Direction, *, is_stop: bool) -> tuple[int, float] | None:
        if level is None:
            return None
        for idx, price in enumerate(path):
            if idx == 0:
                prev = price
                if self._price_satisfies(price, level, direction, is_stop):
                    return idx, price
                continue
            lo, hi = sorted((prev, price))
            if lo <= level <= hi:
                return idx, level
            prev = price
        return None

    @staticmethod
    def _price_satisfies(price: float, level: float, direction: Direction, is_stop: bool) -> bool:
        if is_stop:
            return price >= level if direction == "long" else price <= level
        return price <= level if direction == "long" else price >= level

    def _fill_order(self, order: Order, price: float, runtime: PineRuntime, bar: Bar, fill_source: str = "ohlc_path") -> None:
        qty = self._resolved_order_qty(order, price)
        if order.kind == "entry":
            qty = self._entry_qty_with_reversal_and_pyramiding(order, qty)
            if qty <= 0:
                order.status = "cancelled"
                return
        if order.kind in {"exit", "close"}:
            qty = min(qty, abs(self._available_exit_qty(order.from_entry)))
            if qty <= 0:
                order.status = "cancelled"
                return
        fill_price = self._apply_slippage(price, order.direction)
        commission = self._commission(qty, fill_price)
        order.fill_source = fill_source
        self._apply_position_fill(order, qty, fill_price, commission, runtime, bar)
        order.status = "filled"
        order.filled_qty = qty
        order.fill_price = fill_price
        self.fills.append(Fill(order.id, order.direction, qty, fill_price, commission, runtime.bar_index + 1, bar.time, order.kind, fill_source))
        if order.oca_name:
            for other in self.pending_orders:
                if other is not order and other.oca_name == order.oca_name:
                    other.status = "cancelled"

    def _apply_position_fill(self, order: Order, qty: float, price: float, commission: float, runtime: PineRuntime, bar: Bar) -> None:
        signed = qty if order.direction == "long" else -qty
        if self.position_size == 0 or self.position_size * signed > 0:
            self._lots.append(_OpenLot(order.id, "long" if signed > 0 else "short", qty, price, bar.time, runtime.bar_index + 1, commission))
            self.equity -= commission
        else:
            remaining = qty
            for lot in list(self._lots):
                if remaining <= 0:
                    break
                if order.from_entry and lot.entry_id != order.from_entry:
                    continue
                close_qty = min(lot.qty, remaining)
                profit = (price - lot.entry_price) * close_qty if lot.direction == "long" else (lot.entry_price - price) * close_qty
                prorated_entry_commission = lot.commission * (close_qty / lot.qty) if lot.qty else 0.0
                total_commission = commission * (close_qty / qty) + prorated_entry_commission
                net_profit = profit - total_commission
                self.netprofit += net_profit
                self.grossprofit += max(net_profit, 0.0)
                self.grossloss += min(net_profit, 0.0)
                self.equity += net_profit
                self.closedtrades += 1
                if net_profit > 0:
                    self.wintrades += 1
                elif net_profit < 0:
                    self.losstrades += 1
                else:
                    self.eventrades += 1
                self.closed_trade_log.append(Trade(lot.entry_id, lot.direction, lot.entry_time, lot.entry_bar_index, lot.entry_price, bar.time, runtime.bar_index + 1, price, close_qty, total_commission, net_profit, net_profit / (lot.entry_price * close_qty) * 100 if lot.entry_price and close_qty else 0.0, order.id, order.fill_source))
                lot.qty -= close_qty
                lot.commission -= prorated_entry_commission
                remaining -= close_qty
                if lot.qty <= 1e-12:
                    self._lots.remove(lot)
            if remaining > 1e-12 and order.kind in {"entry", "order"}:
                self._lots.append(_OpenLot(order.id, "long" if signed > 0 else "short", remaining, price, bar.time, runtime.bar_index + 1, commission * (remaining / qty)))
        self._recompute_position(price)

    def _recompute_position(self, mark_price: float) -> None:
        long_qty = sum(l.qty for l in self._lots if l.direction == "long")
        short_qty = sum(l.qty for l in self._lots if l.direction == "short")
        self.position_size = long_qty - short_qty
        if self._lots:
            total = sum(l.qty for l in self._lots)
            self.position_avg_price = sum(l.qty * l.entry_price for l in self._lots) / total
            self.position_entry_name = self._lots[0].entry_id
        else:
            self.position_avg_price = 0.0
            self.position_entry_name = None
        self.opentrades = len(self._lots)
        self.open_trade_log = [Trade(l.entry_id, l.direction, l.entry_time, l.entry_bar_index, l.entry_price, None, None, None, l.qty, l.commission, 0.0, 0.0, None, None) for l in self._lots]
        self._mark_to_market(mark_price)

    def _mark_to_market(self, price: float) -> None:
        self.openprofit = sum(((price - l.entry_price) if l.direction == "long" else (l.entry_price - price)) * l.qty - l.commission for l in self._lots)
        self.equity = self.initial_capital + self.netprofit + self.openprofit

    def _entry_qty_with_reversal_and_pyramiding(self, order: Order, qty: float) -> float:
        same_direction = (self.position_size >= 0 and order.direction == "long") or (self.position_size <= 0 and order.direction == "short")
        if same_direction and self.position_size != 0:
            same_lots = sum(1 for l in self._lots if l.direction == order.direction)
            if same_lots >= self.pyramiding:
                return 0.0
        if self.position_size and not same_direction:
            return qty + abs(self.position_size)
        return qty

    def _resolved_order_qty(self, order: Order, price: float) -> float:
        if order.qty is not None:
            return float(order.qty)
        if self.default_qty_type == "fixed":
            return self.default_qty_value
        if self.default_qty_type == "cash":
            return self.default_qty_value / price
        if self.default_qty_type == "percent_of_equity":
            return self.equity * self.default_qty_value / 100.0 / price
        raise PineStrategyError(f"Unsupported default_qty_type {self.default_qty_type!r}", code=PL_UNSUPPORTED_STRATEGY_SETTING)

    def _resolve_exit_qty(self, qty: float | None, qty_percent: float | None, available: float) -> float:
        if qty is not None:
            return float(qty)
        if qty_percent is not None:
            return available * float(qty_percent) / 100.0
        return available

    def _available_exit_qty(self, from_entry: str | None) -> float:
        lots = self._lots if from_entry is None else [l for l in self._lots if l.entry_id == from_entry]
        sign = 1.0 if self.position_size >= 0 else -1.0
        return sign * sum(l.qty for l in lots)

    def _apply_slippage(self, price: float, direction: Direction) -> float:
        return price + self.slippage if direction == "long" else price - self.slippage

    def _commission(self, qty: float, price: float) -> float:
        if self.commission_type == "percent":
            return abs(qty * price) * self.commission_value / 100.0
        if self.commission_type == "cash_per_order":
            return self.commission_value
        if self.commission_type == "cash_per_contract":
            return abs(qty) * self.commission_value
        raise PineStrategyError(f"Unsupported commission_type {self.commission_type!r}", code=PL_UNSUPPORTED_STRATEGY_SETTING)

    def _execution_path(self, runtime: PineRuntime, bar: Bar, intrabar_bars: list[Bar] | None) -> tuple[list[float], str]:
        if not self.use_bar_magnifier:
            return self.ohlc_path(bar), "ohlc_path"
        bars = intrabar_bars
        if bars is None and runtime.intrabar_provider is not None:
            bars = runtime.intrabar_provider.get_intrabar_bars(runtime.syminfo.tickerid, bar, None)
        if bars and self._validate_intrabar_bars(bar, bars):
            return self._intrabar_path(bars), "intrabar"
        message = "Bar Magnifier requested but valid intrabar data is missing for chart bar"
        if self.declaration.strict_tv_parity or runtime.config.strict_tv_parity or runtime.config.diagnostics_as_errors:
            raise PineStrategyError(message, code=PL_MISSING_INTRABAR_DATA)
        self._emit(runtime, PL_WARNING_BAR_MAGNIFIER_FALLBACK, message, bar_time=bar.time)
        return self.ohlc_path(bar), "ohlc_path"

    def _validate_intrabar_bars(self, chart_bar: Bar, bars: list[Bar]) -> bool:
        last_time: int | None = None
        chart_close = chart_bar.time_close
        for intrabar in bars:
            if intrabar.time < chart_bar.time or (chart_close is not None and intrabar.time > chart_close):
                return False
            if last_time is not None and intrabar.time <= last_time:
                return False
            last_time = intrabar.time
        return True

    def _intrabar_path(self, bars: list[Bar]) -> list[float]:
        path: list[float] = []
        for bar in bars:
            path.extend(self.ohlc_path(bar))
        return path

    def _emit(self, runtime: PineRuntime | None, code: str, message: str, **extra: object) -> None:
        target = runtime.config if runtime is not None else self._diagnostics_target
        if target is not None and hasattr(target, "emit_diagnostic"):
            target.emit_diagnostic(code, message, **extra)
