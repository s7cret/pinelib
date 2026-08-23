"""Intent-v2 wiring mixed into :class:`StrategyContext`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pinelib.core.runtime import PineRuntime
from pinelib.execution_context import ExecutionContext
from pinelib.strategy.intent_tape import IntentTape
from pinelib.strategy.intent_validation import unknown_source_provenance
from pinelib.strategy.models import Direction, RiskRule


class IntentContextMixin:
    """Own IntentTape identity, callback scopes, and complete event recording."""

    _runtime: PineRuntime | None
    _intent_series_id_explicit: bool
    _intent_instrument_id_explicit: bool
    _intent_timeframe_explicit: bool
    _intent_phase: str
    _intent_recalc_iteration: int
    intent_tape: IntentTape
    risk_rules: list[RiskRule]

    def _initialize_intent_context(
        self,
        *,
        run_id: str,
        strategy_id: str,
        series_id: str,
        instrument_id: str,
        timeframe: str,
        producer_commit: object | None,
        strict_production: bool,
        stack_id: str | None,
        execution_context: ExecutionContext | Mapping[str, Any] | None,
    ) -> None:
        self._intent_series_id_explicit = series_id != "series"
        self._intent_instrument_id_explicit = instrument_id != "instrument"
        self._intent_timeframe_explicit = timeframe != "unspecified"
        self._intent_phase = "BAR_COMMIT"
        self._intent_recalc_iteration = 0
        self.intent_tape = IntentTape(
            run_id=run_id,
            strategy_id=strategy_id,
            series_id=series_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            producer_commit=None if producer_commit is None else str(producer_commit),
            stack_id=stack_id,
            strict_production=strict_production,
            execution_context=execution_context,
        )

    def _attach_intent_runtime_identity(self, runtime: PineRuntime) -> None:
        instrument_id = (
            self.intent_tape.instrument_id
            if self._intent_instrument_id_explicit
            else runtime.syminfo.tickerid
        )
        timeframe = (
            self.intent_tape.timeframe
            if self._intent_timeframe_explicit
            else runtime.timeframe.value
        )
        series_id = (
            self.intent_tape.series_id
            if self._intent_series_id_explicit
            else f"{instrument_id}:{timeframe}"
        )
        self.intent_tape.set_series_identity(
            series_id=series_id,
            instrument_id=instrument_id,
            timeframe=timeframe,
            semantic_profile=str(runtime.config.semantic_profile),
        )

    def begin_intent_callback(self, *, phase: str, recalc_iteration: int = 0) -> None:
        """Open a deterministic intent invocation scope for one strategy callback."""

        self._intent_phase = phase
        self._intent_recalc_iteration = recalc_iteration
        bar_index, bar_time = self._intent_bar_identity()
        self.intent_tape.begin_callback(
            bar_index=bar_index,
            bar_open_time_utc_ms=bar_time,
            phase=phase,
            recalc_iteration=recalc_iteration,
        )

    def commit_intents_for_current_bar(self) -> None:
        """Freeze the active bar's intent events at the BAR_COMMIT boundary."""

        bar_index, bar_time = self._intent_bar_identity()
        self.intent_tape.commit_bar(
            bar_index=bar_index,
            bar_open_time_utc_ms=bar_time,
        )

    def risk_allow_entry_in(self, direction: str) -> None:
        rule = RiskRule("allow_entry_in", direction=direction)
        self._record_intent(
            "risk",
            command_id="allow_entry_in",
            risk_rule="allow_entry_in",
            risk_value=0,
            risk_unit=direction,
            risk_scope="entries",
        )
        self.risk_rules.append(rule)

    def risk_max_drawdown(self, value: float, type: str) -> None:
        rule = RiskRule("max_drawdown", float(value), type)
        self._record_intent(
            "risk",
            command_id="max_drawdown",
            risk_rule="max_drawdown",
            risk_value=value,
            risk_unit=type,
            risk_scope="strategy",
        )
        self.risk_rules.append(rule)

    def risk_max_intraday_loss(self, value: float, type: str) -> None:
        rule = RiskRule("max_intraday_loss", float(value), type)
        self._record_intent(
            "risk",
            command_id="max_intraday_loss",
            risk_rule="max_intraday_loss",
            risk_value=value,
            risk_unit=type,
            risk_scope="intraday",
        )
        self.risk_rules.append(rule)

    def risk_max_position_size(self, value: float, type: str = "fixed") -> None:
        rule = RiskRule("max_position_size", float(value), type)
        self._record_intent(
            "risk",
            command_id="max_position_size",
            risk_rule="max_position_size",
            risk_value=value,
            risk_unit=type,
            risk_scope="strategy",
        )
        self.risk_rules.append(rule)

    def risk_max_cons_loss_days(self, value: float, type: str = "fixed") -> None:
        rule = RiskRule("max_cons_loss_days", float(value), type)
        self._record_intent(
            "risk",
            command_id="max_cons_loss_days",
            risk_rule="max_cons_loss_days",
            risk_value=value,
            risk_unit=type,
            risk_scope="strategy",
        )
        self.risk_rules.append(rule)

    def risk_max_intraday_filled_orders(self, value: float, type: str = "fixed") -> None:
        rule = RiskRule("max_intraday_filled_orders", float(value), type)
        self._record_intent(
            "risk",
            command_id="max_intraday_filled_orders",
            risk_rule="max_intraday_filled_orders",
            risk_value=value,
            risk_unit=type,
            risk_scope="intraday",
        )
        self.risk_rules.append(rule)

    def _record_intent(
        self,
        kind: str,
        *,
        command_id: str,
        order_id: str | None = None,
        direction: Direction | None = None,
        qty: object = None,
        qty_percent: object = None,
        stop: object = None,
        limit: object = None,
        profit: object = None,
        loss: object = None,
        trail_price: object = None,
        trail_points: object = None,
        trail_offset: object = None,
        from_entry: str | None = None,
        oca_name: str | None = None,
        oca_type: str | None = None,
        comment: str | None = None,
        immediately: bool | None = None,
        risk_rule: str | None = None,
        risk_value: object = None,
        risk_unit: str | None = None,
        risk_scope: str | None = None,
        source_map: object | None = None,
    ) -> None:
        bar_index, bar_time = self._intent_bar_identity()
        self.intent_tape.record(
            kind,
            command_id=command_id,
            order_id=order_id,
            direction=direction,
            qty=qty,
            qty_percent=qty_percent,
            stop=stop,
            limit=limit,
            profit=profit,
            loss=loss,
            trail_price=trail_price,
            trail_points=trail_points,
            trail_offset=trail_offset,
            from_entry=from_entry,
            oca_name=oca_name,
            oca_type=oca_type,
            comment=comment,
            immediately=immediately,
            risk_rule=risk_rule,
            risk_value=risk_value,
            risk_unit=risk_unit,
            risk_scope=risk_scope,
            bar_index=bar_index,
            bar_open_time_utc_ms=bar_time,
            phase=self._intent_phase,
            recalc_iteration=self._intent_recalc_iteration,
            source_span=(unknown_source_provenance() if source_map is None else source_map),
        )

    def _intent_bar_identity(self) -> tuple[int, int]:
        runtime = self._runtime
        if runtime is None:
            return 0, 0
        bar_time = int(runtime.current_bar.time) if runtime.current_bar is not None else 0
        exposed_index = getattr(getattr(runtime, "bar_index_series", None), "current", None)
        if isinstance(exposed_index, int) and not isinstance(exposed_index, bool):
            bar_index = exposed_index
        else:
            bar_index = max(0, int(runtime.bar_index))
        return max(0, bar_index), max(0, bar_time)
