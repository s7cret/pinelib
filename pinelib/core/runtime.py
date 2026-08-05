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
from pinelib.plot import PlotRecorder
from pinelib.request.providers import DataProvider, IntrabarDataProvider, LowerTfQueryMetadata
from pinelib.version import RUNTIME_CONTRACT_VERSION
from pinelib.visual import VisualRecorder


@dataclass(slots=True)
class PineRuntime:
    symbol_info: SymbolInfo
    timeframe: TimeframeInfo
    data_provider: DataProvider | None = None
    config: RuntimeConfig = field(default_factory=RuntimeConfig)
    intrabar_provider: IntrabarDataProvider | None = None
    bar_index_offset: int = 0

    contract_version: str = field(init=False, default=RUNTIME_CONTRACT_VERSION)
    bar_index: int = field(init=False, default=-1)
    current_bar: Bar | None = field(init=False, default=None)
    chart_bars: list[Bar] = field(init=False, default_factory=list)
    series_registry: dict[str, Series[Any]] = field(init=False, default_factory=dict)
    indicator_state: dict[str, object] = field(init=False, default_factory=dict)
    varip_state: dict[str, object] = field(init=False, default_factory=dict)
    strategy: object | None = field(init=False, default=None)
    request_depth: int = field(init=False, default=0)
    request_security_cache: dict[tuple[object, ...], dict[str, object]] = field(
        init=False, default_factory=dict
    )
    request_lower_tf_cache: dict[tuple[object, ...], list[Bar]] = field(
        init=False, default_factory=dict
    )
    request_data_end_ms: int | None = field(init=False, default=None)
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
        exposed_index = self._exposed_bar_index(current_index)
        self.barstate = BarStateInfo(
            isfirst=exposed_index == 0,
            islast=True,
            ishistory=True,
            isrealtime=False,
            isnew=True,
            isconfirmed=False,
            islastconfirmedhistory=False,
        )
        for series in self.series_registry.values():
            series._between_bars = False
        self._set_builtin_current(effective_bar, exposed_index)

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
        exposed_index = self._exposed_bar_index(current_index)
        self.barstate = BarStateInfo(
            isfirst=exposed_index == 0,
            islast=True,
            ishistory=False,
            isrealtime=True,
            isnew=True,
            isconfirmed=False,
            islastconfirmedhistory=False,
        )
        for series in self.series_registry.values():
            series._between_bars = False
        self._set_builtin_current(effective_bar, exposed_index)

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
        exposed_index = self._exposed_bar_index(current_index)
        self.barstate = BarStateInfo(
            isfirst=exposed_index == 0,
            islast=True,
            ishistory=False,
            isrealtime=True,
            isnew=False,
            isconfirmed=bool(tick.is_final),
            islastconfirmedhistory=False,
        )
        self._set_builtin_current(updated, exposed_index)
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
        exposed_index = self._exposed_bar_index(self.bar_index)
        was_realtime = self.barstate.isrealtime
        self.barstate = BarStateInfo(
            isfirst=exposed_index == 0,
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
            "request_security_cache": copy.deepcopy(self.request_security_cache),
            "request_lower_tf_cache": copy.deepcopy(self.request_lower_tf_cache),
            "request_data_end_ms": self.request_data_end_ms,
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
        required_fields = {
            "bar_index",
            "current_bar",
            "chart_bars",
            "series",
            "indicator_state",
            "barstate",
            "request_depth",
            "request_security_cache",
            "request_lower_tf_cache",
            "request_data_end_ms",
            "lower_tf_metadata_log",
            "plot_recorder",
            "visual",
            "request_namespace",
        }
        allowed_fields = required_fields | {"varip_state"}
        missing = sorted(required_fields - state.keys())
        unknown = sorted(state.keys() - allowed_fields)
        if missing or unknown:
            raise PineRuntimeError(
                "PineRuntime snapshot schema mismatch: " f"missing={missing!r}, unknown={unknown!r}"
            )
        series_state = state["series"]
        if not isinstance(series_state, dict):
            raise PineRuntimeError("PineRuntime snapshot series must be a dict")
        expected_series = set(self.series_registry)
        snapshot_series = set(series_state)
        if snapshot_series != expected_series:
            raise PineRuntimeError(
                "PineRuntime snapshot series mismatch: "
                f"missing={sorted(expected_series - snapshot_series)!r}, "
                f"unknown={sorted(snapshot_series - expected_series)!r}"
            )
        for name, payload in series_state.items():
            if not isinstance(payload, dict) or set(payload) != {"current", "history"}:
                raise PineRuntimeError(
                    f"PineRuntime snapshot series {name!r} must contain current/history"
                )
            if not isinstance(payload["history"], list):
                raise PineRuntimeError(
                    f"PineRuntime snapshot series {name!r} history must be a list"
                )
        bar_index = state["bar_index"]
        if isinstance(bar_index, bool) or not isinstance(bar_index, int):
            raise PineRuntimeError("PineRuntime snapshot bar_index must be an integer")
        current_bar = state["current_bar"]
        if current_bar is not None and not isinstance(current_bar, Bar):
            raise PineRuntimeError("PineRuntime snapshot current_bar must be a Bar or None")
        chart_bars = state["chart_bars"]
        if not isinstance(chart_bars, list) or not all(isinstance(bar, Bar) for bar in chart_bars):
            raise PineRuntimeError("PineRuntime snapshot chart_bars must be a list of Bar")
        dict_fields = (
            "indicator_state",
            "request_security_cache",
            "request_lower_tf_cache",
        )
        for field_name in dict_fields:
            if not isinstance(state[field_name], dict):
                raise PineRuntimeError(f"PineRuntime snapshot {field_name} must be a dict")
        if "varip_state" in state and not isinstance(state["varip_state"], dict):
            raise PineRuntimeError("PineRuntime snapshot varip_state must be a dict")
        if not isinstance(state["barstate"], BarStateInfo):
            raise PineRuntimeError("PineRuntime snapshot barstate must be BarStateInfo")
        request_depth = state["request_depth"]
        if (
            isinstance(request_depth, bool)
            or not isinstance(request_depth, int)
            or request_depth < 0
        ):
            raise PineRuntimeError(
                "PineRuntime snapshot request_depth must be a non-negative integer"
            )
        request_data_end_ms = state["request_data_end_ms"]
        if request_data_end_ms is not None and (
            isinstance(request_data_end_ms, bool) or not isinstance(request_data_end_ms, int)
        ):
            raise PineRuntimeError(
                "PineRuntime snapshot request_data_end_ms must be an integer or None"
            )
        if not isinstance(state["lower_tf_metadata_log"], list):
            raise PineRuntimeError("PineRuntime snapshot lower_tf_metadata_log must be a list")
        if not isinstance(state["plot_recorder"], PlotRecorder):
            raise PineRuntimeError("PineRuntime snapshot plot_recorder must be a PlotRecorder")
        if not isinstance(state["visual"], VisualRecorder):
            raise PineRuntimeError("PineRuntime snapshot visual must be a VisualRecorder")
        request_namespace = state["request_namespace"]
        if request_namespace is not None and not isinstance(request_namespace, str):
            raise PineRuntimeError(
                "PineRuntime snapshot request_namespace must be a string or None"
            )
        try:
            validated = copy.deepcopy(state)
        except Exception as exc:
            raise PineRuntimeError(
                f"PineRuntime snapshot cannot be detached: {type(exc).__name__}: {exc}"
            ) from exc

        self.bar_index = bar_index
        self.current_bar = validated["current_bar"]
        self.chart_bars = validated["chart_bars"]
        validated_series = validated["series"]
        for name, payload in validated_series.items():
            series = self.series_registry[name]
            series._current = payload["current"]
            series._history = payload["history"]
        self.indicator_state = validated["indicator_state"]
        if "varip_state" in validated:
            self.varip_state = validated["varip_state"]
        self.barstate = validated["barstate"]
        self.request_depth = request_depth
        self.request_security_cache = validated["request_security_cache"]
        self.request_lower_tf_cache = validated["request_lower_tf_cache"]
        self.request_data_end_ms = request_data_end_ms
        self.lower_tf_metadata_log = validated["lower_tf_metadata_log"]
        self.plot_recorder = validated["plot_recorder"]
        self.visual = validated["visual"]
        self.request_namespace = request_namespace

    def get_varip_state(self, state_id: str, factory: Any) -> object:
        if state_id not in self.varip_state:
            self.varip_state[state_id] = factory()
        return self.varip_state[state_id]

    def reset_varip_state(self) -> None:
        self.varip_state.clear()

    def _exposed_bar_index(self, local_index: int) -> int:
        return local_index + self.bar_index_offset

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

    def expr_history(self, value: Any, offset: int, state_id: str) -> Any:
        """History for generated scalar expression outputs.

        Pine treats a runtime expression call result as a series over bars, so
        generated code must materialize that scalar under a stable identity
        before applying the history offset.
        """
        dtype = "bool" if isinstance(value, bool) else "float"
        safe_id = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in state_id)
        series = self.series(f"__expr_history_{safe_id}", dtype=dtype)
        series.set_current(value)
        return series[offset]

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
