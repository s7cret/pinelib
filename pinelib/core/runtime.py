from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any

from pinelib.core.bar import Bar
from pinelib.core.inputs import InputRegistry
from pinelib.core.na import na
from pinelib.core.series import Series
from pinelib.core.timefunc import TimeFunctions
from pinelib.core.types import (
    BarStateInfo,
    RuntimeConfig,
    SymbolInfo,
    TickUpdate,
    TimeframeInfo,
    TypeInfo,
)
from pinelib.errors import PineRuntimeError
from pinelib.request.providers import DataProvider, IntrabarDataProvider, LowerTfQueryMetadata
from pinelib.version import RUNTIME_CONTRACT_VERSION
from pinelib.plot import PlotRecorder
from pinelib.visual import VisualRecorder


@dataclass(slots=True)
class PineRuntime:
    symbol_info: SymbolInfo
    timeframe: TimeframeInfo
    data_provider: DataProvider | None = None
    config: RuntimeConfig = field(default_factory=RuntimeConfig)
    intrabar_provider: IntrabarDataProvider | None = None

    contract_version: str = field(init=False, default=RUNTIME_CONTRACT_VERSION)
    bar_index: int = field(init=False, default=-1)
    current_bar: Bar | None = field(init=False, default=None)
    chart_bars: list[Bar] = field(init=False, default_factory=list)
    series_registry: dict[str, Series[Any]] = field(init=False, default_factory=dict)
    indicator_state: dict[str, object] = field(init=False, default_factory=dict)
    varip_state: dict[str, object] = field(init=False, default_factory=dict)
    strategy: object | None = field(init=False, default=None)
    request_depth: int = field(init=False, default=0)
    lower_tf_metadata_log: list[LowerTfQueryMetadata] = field(init=False, default_factory=list)
    timefunc: TimeFunctions = field(init=False, default_factory=TimeFunctions)
    syminfo: SymbolInfo = field(init=False)
    commit_order: list[str] = field(init=False, default_factory=list)
    inputs: InputRegistry = field(init=False)
    barstate: BarStateInfo = field(init=False, default_factory=BarStateInfo)
    plot_recorder: PlotRecorder = field(init=False)
    visual: VisualRecorder = field(init=False)
    request_namespace: str | None = field(init=False, default=None)

    open: Series[float] = field(init=False)
    high: Series[float] = field(init=False)
    low: Series[float] = field(init=False)
    close: Series[float] = field(init=False)
    volume: Series[float] = field(init=False)
    time: Series[int] = field(init=False)
    time_close: Series[int] = field(init=False)
    bar_index_series: Series[int] = field(init=False)

    def __post_init__(self) -> None:
        self.syminfo = self.symbol_info
        if isinstance(self.timeframe, str):
            self.timeframe = TimeframeInfo.from_string(self.timeframe)
        self.inputs = InputRegistry(self.config)
        self.plot_recorder = PlotRecorder()
        self.visual = VisualRecorder(self.config)
        self.open = self.series("open", "float")
        self.high = self.series("high", "float")
        self.low = self.series("low", "float")
        self.close = self.series("close", "float")
        self.volume = self.series("volume", "float")
        self.time = self.series("time", "int")
        self.time_close = self.series("time_close", "int")
        self.bar_index_series = self.series("bar_index", "int")

    def begin_bar(self, bar: Bar) -> None:
        effective_bar = self._normalize_bar(bar)
        self.current_bar = effective_bar
        self.chart_bars.append(effective_bar)
        current_index = self.bar_index + 1
        self.barstate = BarStateInfo(
            isfirst=current_index == 0,
            islast=True,
            ishistory=True,
            isrealtime=False,
            isnew=True,
            isconfirmed=False,
            islastconfirmedhistory=False,
        )
        for series in self.series_registry.values():
            series._between_bars = False
        self._set_builtin_current(effective_bar, current_index)

    def begin_realtime_bar(self, bar: Bar) -> None:
        """Open a deterministic realtime bar without committing it.

        Callers may then feed explicit :class:`TickUpdate` values through
        :meth:`update_realtime_tick`. This is intentionally provider-driven;
        missing ticks are not approximated from OHLC.
        """

        effective_bar = self._normalize_bar(bar)
        self.current_bar = effective_bar
        self.chart_bars.append(effective_bar)
        current_index = self.bar_index + 1
        self.barstate = BarStateInfo(
            isfirst=current_index == 0,
            islast=True,
            ishistory=False,
            isrealtime=True,
            isnew=True,
            isconfirmed=False,
            islastconfirmedhistory=False,
        )
        for series in self.series_registry.values():
            series._between_bars = False
        self._set_builtin_current(effective_bar, current_index)

    def update_realtime_tick(self, tick: TickUpdate) -> Bar:
        if self.current_bar is None:
            raise PineRuntimeError("update_realtime_tick() called without an active realtime bar")
        if not self.barstate.isrealtime:
            raise PineRuntimeError("update_realtime_tick() requires begin_realtime_bar()")
        if tick.time is not None:
            if tick.time < self.current_bar.time:
                raise PineRuntimeError("Realtime tick time cannot precede the active bar")
            if self.current_bar.time_close is not None and tick.time > self.current_bar.time_close:
                raise PineRuntimeError("Realtime tick time cannot exceed active bar time_close")
        updated = Bar(
            time=self.current_bar.time,
            open=self.current_bar.open,
            high=max(self.current_bar.high, tick.price),
            low=min(self.current_bar.low, tick.price),
            close=tick.price,
            volume=self.current_bar.volume + tick.volume,
            time_close=self.current_bar.time_close,
        )
        self.current_bar = updated
        self.chart_bars[-1] = updated
        current_index = self.bar_index + 1
        self.barstate = BarStateInfo(
            isfirst=current_index == 0,
            islast=True,
            ishistory=False,
            isrealtime=True,
            isnew=False,
            isconfirmed=bool(tick.is_final),
            islastconfirmedhistory=False,
        )
        self._set_builtin_current(updated, current_index)
        return updated

    def end_bar(self) -> None:
        if self.current_bar is None:
            raise PineRuntimeError("end_bar() called without an active bar")
        for name in self.commit_order:
            series = self.series_registry[name]
            series.commit_current()
            # Only mark between_bars for historical bars. Realtime bars
            # stay 'during bar' (between_bars=False) since the bar is still live.
            if not self.barstate.isrealtime:
                series.mark_between_bars()
        self.bar_index += 1
        was_realtime = self.barstate.isrealtime
        self.barstate = BarStateInfo(
            isfirst=self.bar_index == 0,
            islast=True,
            ishistory=not was_realtime,
            isrealtime=was_realtime,
            isnew=False,
            isconfirmed=True,
            islastconfirmedhistory=self.barstate.islastconfirmedhistory,
        )

    def set_last_confirmed_history(self, value: bool = True) -> None:
        self.barstate = replace(self.barstate, islastconfirmedhistory=value)

    def export_state(self, *, include_varip: bool = True) -> dict[str, object]:
        """Export a detached runtime checkpoint.

        Realtime rollback callers should use ``include_varip=False`` so normal
        runtime state rolls back while ``varip`` storage survives between tick
        attempts. Resume/export callers can keep the default and capture varip.
        """

        snapshot = {
            "bar_index": self.bar_index,
            "current_bar": copy.deepcopy(self.current_bar),
            "chart_bars": copy.deepcopy(self.chart_bars),
            "series": {
                name: {
                    "current": copy.deepcopy(series._current),
                    "history": copy.deepcopy(series._history),
                }
                for name, series in self.series_registry.items()
            },
            "indicator_state": copy.deepcopy(self.indicator_state),
            "barstate": copy.deepcopy(self.barstate),
            "request_depth": self.request_depth,
            "lower_tf_metadata_log": copy.deepcopy(self.lower_tf_metadata_log),
            "plot_recorder": copy.deepcopy(self.plot_recorder),
            "visual": copy.deepcopy(self.visual),
            "request_namespace": self.request_namespace,
        }
        if include_varip:
            snapshot["varip_state"] = copy.deepcopy(self.varip_state)
        return snapshot

    def restore_state(self, state: object) -> None:
        if not isinstance(state, dict):
            raise PineRuntimeError("PineRuntime restore_state() expects a dict snapshot")
        series_state = state.get("series", {})
        if not isinstance(series_state, dict):
            raise PineRuntimeError("PineRuntime snapshot is missing series state")
        self.bar_index = int(state.get("bar_index", -1))
        self.current_bar = copy.deepcopy(state.get("current_bar"))
        self.chart_bars = copy.deepcopy(state.get("chart_bars", []))
        for name, payload in series_state.items():
            if name not in self.series_registry or not isinstance(payload, dict):
                continue
            series = self.series_registry[name]
            series._current = copy.deepcopy(payload.get("current", na))
            history = payload.get("history", [])
            series._history = copy.deepcopy(history if isinstance(history, list) else [])
        self.indicator_state = copy.deepcopy(state.get("indicator_state", {}))
        if "varip_state" in state:
            self.varip_state = copy.deepcopy(state.get("varip_state", {}))
        self.barstate = copy.deepcopy(state.get("barstate", BarStateInfo()))
        self.request_depth = int(state.get("request_depth", 0))
        self.lower_tf_metadata_log = copy.deepcopy(state.get("lower_tf_metadata_log", []))
        self.plot_recorder = copy.deepcopy(state.get("plot_recorder", PlotRecorder()))
        self.visual = copy.deepcopy(state.get("visual", self.visual))
        self.request_namespace = state.get("request_namespace")

    def get_varip_state(self, state_id: str, factory: Any) -> object:
        if state_id not in self.varip_state:
            self.varip_state[state_id] = factory()
        return self.varip_state[state_id]

    def reset_varip_state(self) -> None:
        self.varip_state.clear()

    def _set_builtin_current(self, bar: Bar, current_index: int) -> None:
        self.open.set_current(bar.open)
        self.high.set_current(bar.high)
        self.low.set_current(bar.low)
        self.close.set_current(bar.close)
        self.volume.set_current(bar.volume)
        self.time.set_current(bar.time)
        self.time_close.set_current(bar.time_close)
        self.bar_index_series.set_current(current_index)

    def history(self, src: Any, offset: int) -> Any:
        """Pine Script history() built-in.

        Returns the value of ``src`` ``offset`` bars ago.
        For Series: returns Series[offset].
        For scalars: returns the scalar unchanged.
        """
        if isinstance(src, Series):
            return src[offset]
        # Scalar/constant — return as-is
        return src

    def series(
        self,
        name: str,
        dtype: str,
        initial: object = na,
        type_info: TypeInfo | None = None,
    ) -> Series[Any]:
        existing = self.series_registry.get(name)
        if existing is not None:
            if existing.dtype != dtype:
                raise PineRuntimeError(
                    f"Series {name!r} already exists with dtype {existing.dtype!r}"
                )
            return existing
        series = Series[Any](
            name=name,
            dtype=dtype,
            initial=initial,
            type_info=type_info,
            runtime_config=self.config,
        )
        self.series_registry[name] = series
        self.commit_order.append(name)
        return series

    def get_indicator_state(self, state_id: str, factory: Any) -> object:
        if state_id not in self.indicator_state:
            self.indicator_state[state_id] = factory()
        return self.indicator_state[state_id]

    def guard_recalc_count(self, count: int) -> None:
        if count > self.config.max_recalculations_per_bar:
            raise PineRuntimeError(
                "Maximum strategy recalculations per bar exceeded",
                context=None,
            )

    def spawn_child_context(self, *, symbol: str, timeframe: str, namespace: str) -> PineRuntime:
        child = PineRuntime(
            symbol_info=SymbolInfo(
                tickerid=symbol,
                timezone=self.syminfo.timezone,
                session=self.syminfo.session,
                mintick=self.syminfo.mintick,
                exchange=self.syminfo.exchange,
                prefix=self.syminfo.prefix,
                description=self.syminfo.description,
            ),
            timeframe=TimeframeInfo.from_string(timeframe),
            data_provider=self.data_provider,
            config=self.config,
            intrabar_provider=self.intrabar_provider,
        )
        child.request_namespace = namespace
        child.indicator_state = {}
        child.lower_tf_metadata_log = self.lower_tf_metadata_log
        return child

    def _normalize_bar(self, bar: Bar) -> Bar:
        if bar.time_close is not None:
            return bar
        if not self.config.allow_incomplete_bar_time_close:
            raise PineRuntimeError(
                "Bar.time_close is required when runtime config forbids inference"
            )
        timeframe = self.timeframe
        if timeframe.interval_ms is None:
            raise PineRuntimeError(
                "Bar.time_close is missing and timeframe close inference is unavailable"
            )
        return bar.with_time_close(bar.time + timeframe.interval_ms - 1)
