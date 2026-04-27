from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pinelib.core.bar import Bar
from pinelib.core.inputs import InputRegistry
from pinelib.core.na import na
from pinelib.core.series import Series
from pinelib.core.timefunc import TimeFunctions
from pinelib.core.types import BarStateInfo, RuntimeConfig, SymbolInfo, TickUpdate, TimeframeInfo, TypeInfo
from pinelib.errors import PineRuntimeError
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

    contract_version: str = field(init=False, default=RUNTIME_CONTRACT_VERSION)
    bar_index: int = field(init=False, default=-1)
    current_bar: Bar | None = field(init=False, default=None)
    chart_bars: list[Bar] = field(init=False, default_factory=list)
    series_registry: dict[str, Series[Any]] = field(init=False, default_factory=dict)
    indicator_state: dict[str, object] = field(init=False, default_factory=dict)
    strategy: object | None = field(init=False, default=None)
    request_depth: int = field(init=False, default=0)
    lower_tf_metadata_log: list[LowerTfQueryMetadata] = field(init=False, default_factory=list)
    timefunc: TimeFunctions = field(init=False, default_factory=TimeFunctions)
    syminfo: SymbolInfo = field(init=False)
    commit_order: list[str] = field(init=False, default_factory=list)
    inputs: InputRegistry = field(init=False)
    barstate: BarStateInfo = field(init=False, default_factory=BarStateInfo)
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
            self.series_registry[name].commit_current()
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

    def _set_builtin_current(self, bar: Bar, current_index: int) -> None:
        self.open.set_current(bar.open)
        self.high.set_current(bar.high)
        self.low.set_current(bar.low)
        self.close.set_current(bar.close)
        self.volume.set_current(bar.volume)
        self.time.set_current(bar.time)
        self.time_close.set_current(bar.time_close)
        self.bar_index_series.set_current(current_index)

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
                raise PineRuntimeError(f"Series {name!r} already exists with dtype {existing.dtype!r}")
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

    def spawn_child_context(self, *, symbol: str, timeframe: str, namespace: str) -> "PineRuntime":
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
            raise PineRuntimeError("Bar.time_close is required when runtime config forbids inference")
        timeframe = self.timeframe
        if timeframe.interval_ms is None:
            raise PineRuntimeError("Bar.time_close is missing and timeframe close inference is unavailable")
        return bar.with_time_close(bar.time + timeframe.interval_ms - 1)
