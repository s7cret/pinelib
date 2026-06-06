from __future__ import annotations

from typing import Any

from pinelib.core.bar import Bar
from pinelib.core.runtime import PineRuntime
from pinelib.errors import (
    PL_MARGIN_FIELDS_DIAGNOSTIC,
    PL_UNSUPPORTED_STRATEGY_SETTING,
    PineStrategyError,
    StrategyLedgerUnavailableError,
)
from pinelib.strategy.models import (
    Direction,
    Order,
    OrderKind,
    OrderType,
    RiskRule,
    StrategyDeclaration,
    StrategyLedgerView,
    _StrategyScalarSeries,
)


class StrategyContext:
    """Pine strategy API facade.

    PineLib owns generated-code API compatibility and records order/risk
    intents. Broker-owned state is read through ``StrategyLedgerView``. It does
    not simulate fills, equity, trades, runup, drawdown, or risk enforcement.
    """

    def __init__(self, **kwargs: Any) -> None:
        strategy_ledger_view = kwargs.pop("strategy_ledger_view", None)
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
        self.fill_orders_on_standard_ohlc = self.declaration.fill_orders_on_standard_ohlc
        self.max_bars_back = self.declaration.max_bars_back
        self.qty_step = self.declaration.qty_step
        self.qty_rounding_mode = self.declaration.qty_rounding_mode
        self.pending_orders: list[Order] = []
        self.risk_rules: list[RiskRule] = []
        self._closedtrades = _StrategyScalarSeries(0)
        self._strategy_ledger_view: StrategyLedgerView | None = strategy_ledger_view
        self._diagnostics_target: object | None = None
        self._runtime: PineRuntime | None = None

    @property
    def closedtrades(self) -> _StrategyScalarSeries:
        return self._closedtrades

    @closedtrades.setter
    def closedtrades(self, value: int | float | _StrategyScalarSeries) -> None:
        if isinstance(value, _StrategyScalarSeries):
            self._closedtrades = value
        else:
            self._closedtrades.set_current(value)

    @property
    def fills(self) -> list[object]:
        return self._ledger_sequence("fills")

    @property
    def closed_trade_log(self) -> list[object]:
        return self._ledger_sequence("closed_trade_log")

    @property
    def open_trade_log(self) -> list[object]:
        return self._ledger_sequence("open_trade_log")

    @property
    def equity(self) -> float:
        return self._ledger_float("equity")

    @property
    def netprofit(self) -> float:
        return self._ledger_float("netprofit")

    @property
    def openprofit(self) -> float:
        return self._ledger_float("openprofit")

    @property
    def grossprofit(self) -> float:
        return self._ledger_float("grossprofit")

    @property
    def grossloss(self) -> float:
        return self._ledger_float("grossloss")

    @property
    def position_size(self) -> float:
        return self._ledger_float("position_size")

    @property
    def position_avg_price(self) -> float:
        return self._ledger_float("position_avg_price")

    @property
    def position_entry_name(self) -> str | None:
        return self._ledger_optional_str("position_entry_name")

    @property
    def opentrades(self) -> int:
        return self._ledger_int("opentrades")

    @property
    def wintrades(self) -> int:
        return self._ledger_int("wintrades")

    @property
    def losstrades(self) -> int:
        return self._ledger_int("losstrades")

    @property
    def eventrades(self) -> int:
        return self._ledger_int("eventrades")

    @property
    def max_drawdown(self) -> float:
        return self._ledger_float("max_drawdown")

    @property
    def max_runup(self) -> float:
        return self._ledger_float("max_runup")

    def commit_scalar_history(self) -> None:
        self._closedtrades.commit_current()

    def attach_runtime(self, runtime: PineRuntime) -> None:
        runtime.strategy = self
        self._runtime = runtime
        self._diagnostics_target = runtime.config
        runtime.visual.max_counts["label"] = self.declaration.max_labels_count
        runtime.visual.max_counts["line"] = self.declaration.max_lines_count
        runtime.visual.max_counts["box"] = self.declaration.max_boxes_count
        self._sync_runtime_strategy_flags(runtime)
        self._validate_settings(runtime)

    def attach_strategy_ledger_view(self, ledger_view: StrategyLedgerView) -> None:
        self._strategy_ledger_view = ledger_view

    def _sync_runtime_strategy_flags(self, runtime: PineRuntime) -> None:
        expected = {
            "process_orders_on_close": self.process_orders_on_close,
            "calc_on_order_fills": self.calc_on_order_fills,
            "calc_on_every_tick": self.calc_on_every_tick,
        }
        for name, value in expected.items():
            configured = getattr(runtime.config, name)
            if configured is None:
                setattr(runtime.config, name, value)
            elif bool(configured) != bool(value) and self.declaration.strict_tv_parity:
                raise PineStrategyError(
                    f"RuntimeConfig.{name} conflicts with StrategyContext.{name}",
                    code=PL_UNSUPPORTED_STRATEGY_SETTING,
                )
            else:
                setattr(runtime.config, name, value)

    def _validate_settings(self, runtime: PineRuntime) -> None:
        unsupported: list[str] = []
        if self.backtest_fill_limits_assumption not in (None, 0):
            unsupported.append("backtest_fill_limits_assumption")
        if self.close_entries_rule not in ("FIFO", "ANY"):
            unsupported.append("close_entries_rule")
        if self.fill_orders_on_standard_ohlc is not None:
            unsupported.append("fill_orders_on_standard_ohlc")
        if unsupported:
            msg = "Unsupported strategy settings: " + ", ".join(unsupported)
            if self.declaration.strict_tv_parity or runtime.config.strict_tv_parity:
                raise PineStrategyError(msg, code=PL_UNSUPPORTED_STRATEGY_SETTING)
            self._emit(runtime, PL_UNSUPPORTED_STRATEGY_SETTING, msg, settings=unsupported)
        if self.margin_long != 100.0 or self.margin_short != 100.0:
            self._emit(
                runtime,
                PL_MARGIN_FIELDS_DIAGNOSTIC,
                "margin_long/margin_short are captured as declaration metadata; "
                "broker risk belongs to BacktestEngine",
                margin_long=self.margin_long,
                margin_short=self.margin_short,
            )

    def entry(
        self,
        id: str,
        direction: Direction,
        qty: float | None = None,
        limit: float | None = None,
        stop: float | None = None,
        *,
        comment: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        alert_message: str | None = None,
        disable_alert: bool | None = None,
        source_map: object | None = None,
    ) -> None:
        self._add_order(
            id,
            direction,
            qty,
            limit,
            stop,
            "entry",
            comment=comment,
            oca_name=oca_name,
            oca_type=oca_type,
            alert_message=alert_message,
            disable_alert=disable_alert,
            source_map=source_map,
        )

    def order(
        self,
        id: str,
        direction: Direction,
        qty: float | None = None,
        limit: float | None = None,
        stop: float | None = None,
        comment: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        *,
        source_map: object | None = None,
    ) -> None:
        order = self._make_order(
            id, direction, qty, limit, stop, "order", comment=comment, source_map=source_map
        )
        order.oca_name = oca_name
        order.oca_type = oca_type
        self.pending_orders.append(order)

    def exit(
        self,
        id: str,
        from_entry: str | None = None,
        qty: float | None = None,
        qty_percent: float | None = None,
        limit: float | None = None,
        stop: float | None = None,
        profit: float | None = None,
        loss: float | None = None,
        trail_price: float | None = None,
        trail_points: float | None = None,
        trail_offset: float | None = None,
        *,
        comment: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        comment_profit: str | None = None,
        comment_loss: str | None = None,
        comment_trailing: str | None = None,
        alert_message: str | None = None,
        alert_profit: str | None = None,
        alert_loss: str | None = None,
        alert_trailing: str | None = None,
        disable_alert: bool | None = None,
        source_map: object | None = None,
    ) -> None:
        has_bracket_intent = any(
            value is not None
            for value in (limit, stop, profit, loss, trail_price, trail_points, trail_offset)
        )
        order = self._make_order(
            id, None, qty, limit, stop, "exit", comment=comment, source_map=source_map
        )
        order.qty_percent = qty_percent
        order.profit = profit
        order.loss = loss
        order.from_entry = from_entry
        order.parent_exit_id = id
        order.bracket_group = id if has_bracket_intent else None
        order.oca_name = oca_name
        order.oca_type = oca_type or "reduce"
        order.comment_profit = comment_profit
        order.comment_loss = comment_loss
        order.comment_trailing = comment_trailing
        order.alert_message = alert_message
        order.alert_profit = alert_profit
        order.alert_loss = alert_loss
        order.alert_trailing = alert_trailing
        order.disable_alert = disable_alert
        order.trail_activation = trail_price if trail_price is not None else trail_points
        order.trail_offset = trail_offset
        self.pending_orders.append(order)

    def close(
        self,
        id: str,
        qty: float | None = None,
        qty_percent: float | None = None,
        immediately: bool = False,
        *,
        comment: str | None = None,
        alert_message: str | None = None,
        disable_alert: bool | None = None,
        source_map: object | None = None,
    ) -> None:
        order = self._make_order(
            f"close:{id}",
            None,
            qty,
            None,
            None,
            "close",
            comment=comment,
            alert_message=alert_message,
            disable_alert=disable_alert,
            source_map=source_map,
        )
        order.qty_percent = qty_percent
        order.from_entry = id
        order.immediate = immediately
        self.pending_orders.append(order)

    def close_all(
        self,
        immediately: bool = False,
        *,
        comment: str | None = None,
        source_map: object | None = None,
    ) -> None:
        order = self._make_order(
            "close_all",
            None,
            None,
            None,
            None,
            "close",
            comment=comment,
            source_map=source_map,
        )
        order.immediate = immediately
        self.pending_orders.append(order)

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
        return False

    def update_position_equity_trades_after_fill(self) -> None:
        return None

    def process_orders_for_bar(
        self,
        *,
        runtime: PineRuntime,
        bar: Bar,
        recalc_phase: bool = False,
        intrabar_bars: list[Bar] | None = None,
    ) -> None:
        del runtime, bar, recalc_phase, intrabar_bars
        if self.pending_orders:
            raise PineStrategyError(
                "PineLib StrategyContext records order intents only; "
                "route fills/equity/trades through BacktestEngine",
                code=PL_UNSUPPORTED_STRATEGY_SETTING,
            )

    @staticmethod
    def ohlc_path(bar: Bar) -> list[float]:
        if abs(bar.open - bar.high) < abs(bar.open - bar.low):
            return [bar.open, bar.high, bar.low, bar.close]
        return [bar.open, bar.low, bar.high, bar.close]

    def note_calc_on_every_tick_historical_fallback(self, runtime: PineRuntime) -> None:
        del runtime
        raise PineStrategyError(
            "calc_on_every_tick=True requires BacktestEngine realtime tick execution",
            code=PL_UNSUPPORTED_STRATEGY_SETTING,
        )

    def _add_order(
        self,
        id: str,
        direction: Direction,
        qty: float | None,
        limit: float | None,
        stop: float | None,
        kind: OrderKind,
        *,
        comment: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        alert_message: str | None = None,
        disable_alert: bool | None = None,
        source_map: object | None = None,
    ) -> None:
        self.pending_orders.append(
            self._make_order(
                id,
                direction,
                qty,
                limit,
                stop,
                kind,
                comment=comment,
                oca_name=oca_name,
                oca_type=oca_type,
                alert_message=alert_message,
                disable_alert=disable_alert,
                source_map=source_map,
            )
        )

    def _make_order(
        self,
        id: str,
        direction: Direction | None,
        qty: float | None,
        limit: float | None,
        stop: float | None,
        kind: OrderKind,
        *,
        comment: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        alert_message: str | None = None,
        disable_alert: bool | None = None,
        source_map: object | None = None,
    ) -> Order:
        typ: OrderType = "market"
        if limit is not None and stop is not None:
            typ = "stop_limit"
        elif limit is not None:
            typ = "limit"
        elif stop is not None:
            typ = "stop"
        return Order(
            id=id,
            direction=direction,
            qty=qty,
            type=typ,
            kind=kind,
            limit=limit,
            stop=stop,
            created_bar_index=self._runtime.bar_index if self._runtime is not None else -1,
            created_time=self._runtime.current_bar.time
            if self._runtime is not None and self._runtime.current_bar is not None
            else None,
            comment=comment,
            oca_name=oca_name,
            oca_type=oca_type,
            alert_message=alert_message,
            disable_alert=disable_alert,
            source_map=source_map,
        )

    def closedtrades_entry_price(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_entry_price", index)

    def closedtrades_exit_price(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_exit_price", index)

    def closedtrades_entry_time(self, index: int | float) -> int | type:
        return self._ledger_indexed_or_na("closedtrades_entry_time", index)

    def closedtrades_exit_time(self, index: int | float) -> int | type:
        return self._ledger_indexed_or_na("closedtrades_exit_time", index)

    def closedtrades_profit(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_profit", index)

    def closedtrades_profit_percent(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_profit_percent", index)

    def closedtrades_net_profit(self, index: int | float) -> float | type:
        return self.closedtrades_profit(index)

    def closedtrades_commission(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_commission", index)

    def closedtrades_qty(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_qty", index)

    def closedtrades_side(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("closedtrades_side", index)

    def closedtrades_size(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_size", index)

    def closedtrades_entry_id(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("closedtrades_entry_id", index)

    def closedtrades_exit_id(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("closedtrades_exit_id", index)

    def closedtrades_entry_comment(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("closedtrades_entry_comment", index)

    def closedtrades_exit_comment(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("closedtrades_exit_comment", index)

    def closedtrades_max_runup(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_max_runup", index)

    def closedtrades_max_drawdown(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("closedtrades_max_drawdown", index)

    def closedtrades_entry_bar_index(self, index: int | float) -> int | type:
        return self._ledger_indexed_or_na("closedtrades_entry_bar_index", index)

    def closedtrades_exit_bar_index(self, index: int | float) -> int | type:
        return self._ledger_indexed_or_na("closedtrades_exit_bar_index", index)

    def opentrades_entry_price(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_entry_price", index)

    def opentrades_profit(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_profit", index)

    def opentrades_profit_percent(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_profit_percent", index)

    def opentrades_commission(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_commission", index)

    def opentrades_qty(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_qty", index)

    def opentrades_side(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("opentrades_side", index)

    def opentrades_entry_id(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("opentrades_entry_id", index)

    def opentrades_exit_price(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_exit_price", index)

    def opentrades_exit_time(self, index: int | float) -> int | type:
        return self._ledger_indexed_or_na("opentrades_exit_time", index)

    def opentrades_exit_id(self, index: int | float) -> str | type:
        return self._ledger_indexed_or_na("opentrades_exit_id", index)

    def opentrades_size(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_size", index)

    def opentrades_max_runup(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_max_runup", index)

    def opentrades_max_drawdown(self, index: int | float) -> float | type:
        return self._ledger_indexed_or_na("opentrades_max_drawdown", index)

    def opentrades_entry_bar_index(self, index: int | float) -> int | type:
        return self._ledger_indexed_or_na("opentrades_entry_bar_index", index)

    def risk_allow_entry_in(self, direction: str) -> None:
        self.risk_rules.append(RiskRule("allow_entry_in", direction=direction))

    def risk_max_drawdown(self, value: float, type: str) -> None:
        self.risk_rules.append(RiskRule("max_drawdown", float(value), type))

    def risk_max_intraday_loss(self, value: float, type: str) -> None:
        self.risk_rules.append(RiskRule("max_intraday_loss", float(value), type))

    def risk_max_position_size(self, value: float, type: str = "fixed") -> None:
        self.risk_rules.append(RiskRule("max_position_size", float(value), type))

    def risk_max_intraday_filled_orders(self, value: float, type: str = "fixed") -> None:
        self.risk_rules.append(RiskRule("max_intraday_filled_orders", float(value), type))

    def _ledger_indexed_or_na(self, method_name: str, index: int | float) -> Any:
        from pinelib.core.na import na

        idx = int(index)
        if idx < 0:
            return na
        return self._ledger_metric(method_name, idx)

    def _ledger_metric(self, method_name: str, index: int) -> Any:
        view = self._require_ledger_view(method_name)
        method = getattr(view, method_name, None)
        if not callable(method):
            raise StrategyLedgerUnavailableError(
                f"StrategyLedgerView does not provide {method_name}"
            )
        value = method(index)
        if value is None:
            raise StrategyLedgerUnavailableError(f"{method_name}({index}) is unavailable")
        return value

    def _ledger_float(self, name: str) -> float:
        return float(self._ledger_value(name))

    def _ledger_int(self, name: str) -> int:
        return int(self._ledger_value(name))

    def _ledger_optional_str(self, name: str) -> str | None:
        value = self._ledger_value(name)
        return None if value is None else str(value)

    def _ledger_sequence(self, name: str) -> list[object]:
        value = self._ledger_value(name)
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        raise StrategyLedgerUnavailableError(f"StrategyLedgerView.{name} is not a sequence")

    def _ledger_value(self, name: str) -> Any:
        view = self._require_ledger_view(name)
        if hasattr(view, name):
            return getattr(view, name)
        method = getattr(view, name, None)
        if callable(method):
            return method()
        raise StrategyLedgerUnavailableError(f"StrategyLedgerView does not provide {name}")

    def _require_ledger_view(self, name: str) -> StrategyLedgerView:
        if self._strategy_ledger_view is None:
            raise StrategyLedgerUnavailableError(
                f"strategy.{name} requires a StrategyLedgerView supplied by BacktestEngine"
            )
        return self._strategy_ledger_view

    def _emit(self, runtime: PineRuntime | None, code: str, message: str, **extra: object) -> None:
        target = runtime.config if runtime is not None else self._diagnostics_target
        if target is not None and hasattr(target, "emit_diagnostic"):
            target.emit_diagnostic(code, message, **extra)
