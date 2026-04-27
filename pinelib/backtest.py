from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, cast, runtime_checkable

from pinelib.core.bar import Bar
from pinelib.core.runtime import PineRuntime
from pinelib.core.types import TickUpdate
from pinelib.errors import PineGoldenMismatchError, PineRuntimeError
from pinelib.strategy.context import Fill, StrategyContext, Trade


@runtime_checkable
class GeneratedStrategy(Protocol):
    """Protocol implemented by AST2Python-generated strategy classes."""

    def on_bar(self, runtime: PineRuntime, strategy: StrategyContext) -> None: ...


@dataclass(frozen=True, slots=True)
class StrategySchedule:
    """Controls deterministic strategy execution scheduling."""

    process_orders: bool = True
    calc_on_order_fills: bool = True
    calc_on_every_tick: bool = True
    max_recalculations_per_bar: int | None = None


@dataclass(frozen=True, slots=True)
class BacktestSnapshot:
    bar_index: int
    time: int
    close: float
    equity: float
    netprofit: float
    openprofit: float
    position_size: float
    position_avg_price: float
    fills_count: int
    closedtrades: int


@dataclass(frozen=True, slots=True)
class BacktestReport:
    schema_version: str
    package_version: str
    contract_version: str
    symbol: str
    timeframe: str
    bars: int
    initial_capital: float
    final_equity: float
    netprofit: float
    grossprofit: float
    grossloss: float
    openprofit: float
    max_drawdown: float
    max_runup: float
    closedtrades: int
    opentrades: int
    wintrades: int
    losstrades: int
    eventrades: int
    fills: list[dict[str, object]]
    closed_trades: list[dict[str, object]]
    params: dict[str, object] = field(default_factory=dict)
    params_metadata: dict[str, object] = field(default_factory=dict)
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    snapshots: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class BacktestResult:
    runtime: PineRuntime
    strategy: StrategyContext
    strategy_instance: object
    snapshots: list[BacktestSnapshot]
    report: BacktestReport


def run_generated_strategy(
    strategy_instance: object,
    runtime: PineRuntime,
    strategy: StrategyContext,
    bars: Iterable[Bar],
    *,
    schedule: StrategySchedule | None = None,
    realtime_ticks: Iterable[Iterable[TickUpdate]] | None = None,
) -> BacktestResult:
    """Run generated-like code bar-by-bar using PineRuntime + StrategyContext.

    The generated object may expose ``on_bar(runtime, strategy)`` or be directly callable with
    the same arguments. Orders are processed after each calculation pass. When
    ``calc_on_order_fills`` is enabled in StrategyContext, a guarded recalc loop repeats the
    generated pass after fills until no new fill-triggered calculation is pending.
    """

    if runtime.strategy is not strategy:
        strategy.attach_runtime(runtime)
    schedule = schedule or StrategySchedule()
    snapshots: list[BacktestSnapshot] = []
    callback = _resolve_strategy_callback(strategy_instance)
    max_recalcs = schedule.max_recalculations_per_bar or runtime.config.max_recalculations_per_bar

    bars_list = list(bars)
    ticks_list = [list(ticks) for ticks in realtime_ticks] if realtime_ticks is not None else [[] for _ in bars_list]
    if len(ticks_list) < len(bars_list):
        ticks_list.extend([[] for _ in range(len(bars_list) - len(ticks_list))])
    first_realtime_index = next((idx for idx, ticks in enumerate(ticks_list) if ticks), None)
    last_confirmed_history_index = (first_realtime_index - 1) if first_realtime_index is not None else (len(bars_list) - 1)

    for idx, bar in enumerate(bars_list):
        bar_ticks = ticks_list[idx] if idx < len(ticks_list) else []
        if bar_ticks:
            if not strategy.calc_on_every_tick or not schedule.calc_on_every_tick:
                runtime.begin_bar(bar)
                runtime.set_last_confirmed_history(idx == last_confirmed_history_index)
                active_bar = runtime.current_bar
                if active_bar is None:
                    raise PineRuntimeError("runtime did not set current_bar")
                _run_strategy_pass(callback, runtime, strategy, active_bar, schedule, max_recalcs)
            else:
                runtime.begin_realtime_bar(bar)
                for idx, tick in enumerate(bar_ticks):
                    if idx == len(bar_ticks) - 1 and not tick.is_final:
                        tick = TickUpdate(tick.price, tick.volume, tick.time, True)
                    active_bar = runtime.update_realtime_tick(tick)
                    callback(runtime, strategy)
                    if schedule.process_orders:
                        strategy.process_orders_for_bar(runtime=runtime, bar=active_bar, recalc_phase=idx > 0)
                        _run_fill_recalcs(callback, runtime, strategy, active_bar, schedule, max_recalcs)
        else:
            runtime.begin_bar(bar)
            runtime.set_last_confirmed_history(idx == last_confirmed_history_index)
            if strategy.calc_on_every_tick and schedule.calc_on_every_tick:
                strategy.note_calc_on_every_tick_historical_fallback(runtime)
            active_bar = runtime.current_bar
            if active_bar is None:  # defensive; begin_bar guarantees this
                raise PineRuntimeError("runtime did not set current_bar")
            _run_strategy_pass(callback, runtime, strategy, active_bar, schedule, max_recalcs)
        runtime.end_bar()
        snapshots.append(snapshot_from_state(runtime, strategy))

    report = build_backtest_report(runtime, strategy, strategy_instance, snapshots)
    return BacktestResult(runtime, strategy, strategy_instance, snapshots, report)


def _run_strategy_pass(
    callback: Callable[[PineRuntime, StrategyContext], None],
    runtime: PineRuntime,
    strategy: StrategyContext,
    active_bar: Bar,
    schedule: StrategySchedule,
    max_recalcs: int,
) -> None:
    callback(runtime, strategy)
    if schedule.process_orders:
        strategy.process_orders_for_bar(runtime=runtime, bar=active_bar)
        _run_fill_recalcs(callback, runtime, strategy, active_bar, schedule, max_recalcs)


def _run_fill_recalcs(
    callback: Callable[[PineRuntime, StrategyContext], None],
    runtime: PineRuntime,
    strategy: StrategyContext,
    active_bar: Bar,
    schedule: StrategySchedule,
    max_recalcs: int,
) -> None:
    recalc_count = 0
    while schedule.calc_on_order_fills and strategy.calc_on_order_fills and strategy.has_fill_recalc_pending():
        recalc_count += 1
        if recalc_count > max_recalcs:
            raise PineRuntimeError("Maximum strategy recalculations per bar exceeded")
        runtime.guard_recalc_count(recalc_count)
        strategy.update_position_equity_trades_after_fill()
        callback(runtime, strategy)
        strategy.process_orders_for_bar(runtime=runtime, bar=active_bar, recalc_phase=True)


def snapshot_from_state(runtime: PineRuntime, strategy: StrategyContext) -> BacktestSnapshot:
    bar = runtime.current_bar
    if bar is None:
        raise PineRuntimeError("Cannot snapshot without current bar")
    return BacktestSnapshot(
        bar_index=runtime.bar_index,
        time=bar.time,
        close=bar.close,
        equity=float(strategy.equity),
        netprofit=float(strategy.netprofit),
        openprofit=float(strategy.openprofit),
        position_size=float(strategy.position_size),
        position_avg_price=float(strategy.position_avg_price),
        fills_count=len(strategy.fills),
        closedtrades=int(strategy.closedtrades),
    )


def build_backtest_report(
    runtime: PineRuntime,
    strategy: StrategyContext,
    strategy_instance: object,
    snapshots: Iterable[BacktestSnapshot] = (),
) -> BacktestReport:
    from pinelib.version import PACKAGE_VERSION, RUNTIME_CONTRACT_VERSION

    return BacktestReport(
        schema_version="pinelib.backtest.report.v1",
        package_version=PACKAGE_VERSION,
        contract_version=RUNTIME_CONTRACT_VERSION,
        symbol=runtime.syminfo.tickerid,
        timeframe=runtime.timeframe.value,
        bars=len(runtime.chart_bars),
        initial_capital=float(strategy.initial_capital),
        final_equity=float(strategy.equity),
        netprofit=float(strategy.netprofit),
        grossprofit=float(strategy.grossprofit),
        grossloss=float(strategy.grossloss),
        openprofit=float(strategy.openprofit),
        max_drawdown=float(strategy.max_drawdown),
        max_runup=float(strategy.max_runup),
        closedtrades=int(strategy.closedtrades),
        opentrades=int(strategy.opentrades),
        wintrades=int(strategy.wintrades),
        losstrades=int(strategy.losstrades),
        eventrades=int(strategy.eventrades),
        fills=[_fill_to_dict(fill) for fill in strategy.fills],
        closed_trades=[_trade_to_dict(trade) for trade in strategy.closed_trade_log],
        params=extract_strategy_params(strategy_instance),
        params_metadata=extract_params_metadata(strategy_instance),
        diagnostics=list(runtime.config.diagnostics),
        snapshots=[asdict(snapshot) for snapshot in snapshots],
    )


def extract_strategy_params(strategy_instance: object) -> dict[str, object]:
    candidates = ("params", "PARAMS", "input_values")
    for name in candidates:
        value = getattr(strategy_instance, name, None)
        if isinstance(value, dict):
            return dict(value)
    return {}


def extract_params_metadata(strategy_instance: object) -> dict[str, object]:
    candidates = ("params_metadata", "PARAMS_METADATA", "INPUT_METADATA")
    for name in candidates:
        value = getattr(strategy_instance, name, None)
        if isinstance(value, dict):
            return dict(value)
    return {}


def write_result_snapshot(result: BacktestResult, path: str | Path) -> None:
    payload = {
        "report": result.report.to_dict(),
        "snapshots": [asdict(snapshot) for snapshot in result.snapshots],
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_golden(actual: object, expected: object, *, abs_tol: float = 1e-9, rel_tol: float = 1e-9, path: str = "$") -> None:
    """Compare JSON-like structures with numeric tolerances."""

    import math

    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if not math.isclose(float(actual), float(expected), abs_tol=abs_tol, rel_tol=rel_tol):
            raise PineGoldenMismatchError(f"Golden mismatch at {path}: {actual!r} != {expected!r}")
        return
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            raise PineGoldenMismatchError(f"Golden key mismatch at {path}: {sorted(actual)} != {sorted(expected)}")
        for key in actual:
            compare_golden(actual[key], expected[key], abs_tol=abs_tol, rel_tol=rel_tol, path=f"{path}.{key}")
        return
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            raise PineGoldenMismatchError(f"Golden length mismatch at {path}: {len(actual)} != {len(expected)}")
        for idx, (left, right) in enumerate(zip(actual, expected, strict=True)):
            compare_golden(left, right, abs_tol=abs_tol, rel_tol=rel_tol, path=f"{path}[{idx}]")
        return
    if actual != expected:
        raise PineGoldenMismatchError(f"Golden mismatch at {path}: {actual!r} != {expected!r}")


def _resolve_strategy_callback(strategy_instance: object) -> Callable[[PineRuntime, StrategyContext], None]:
    on_bar = getattr(strategy_instance, "on_bar", None)
    if callable(on_bar):
        return cast(Callable[[PineRuntime, StrategyContext], None], on_bar)
    if callable(strategy_instance):
        return cast(Callable[[PineRuntime, StrategyContext], None], strategy_instance)
    raise PineRuntimeError("Generated strategy must define on_bar(runtime, strategy) or be callable")


def _fill_to_dict(fill: Fill) -> dict[str, object]:
    return asdict(fill)


def _trade_to_dict(trade: Trade) -> dict[str, object]:
    return asdict(trade)
