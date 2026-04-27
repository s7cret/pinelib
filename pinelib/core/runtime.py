from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pinelib.core.bar import Bar
from pinelib.core.inputs import InputRegistry
from pinelib.core.na import na
from pinelib.core.series import Series
from pinelib.core.timefunc import TimeFunctions
from pinelib.core.types import BarStateInfo, RuntimeConfig, SymbolInfo, TimeframeInfo, TypeInfo
from pinelib.errors import PineRuntimeError
from pinelib.request.providers import DataProvider, IntrabarDataProvider
from pinelib.version import RUNTIME_CONTRACT_VERSION


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
    timefunc: TimeFunctions = field(init=False, default_factory=TimeFunctions)
    syminfo: SymbolInfo = field(init=False)
    commit_order: list[str] = field(init=False, default_factory=list)
    inputs: InputRegistry = field(init=False)
    barstate: BarStateInfo = field(init=False, default_factory=BarStateInfo)

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
        )
        self.open.set_current(effective_bar.open)
        self.high.set_current(effective_bar.high)
        self.low.set_current(effective_bar.low)
        self.close.set_current(effective_bar.close)
        self.volume.set_current(effective_bar.volume)
        self.time.set_current(effective_bar.time)
        self.time_close.set_current(effective_bar.time_close)
        self.bar_index_series.set_current(current_index)

    def end_bar(self) -> None:
        if self.current_bar is None:
            raise PineRuntimeError("end_bar() called without an active bar")
        for name in self.commit_order:
            self.series_registry[name].commit_current()
        self.bar_index += 1
        self.barstate = BarStateInfo(
            isfirst=self.bar_index == 0,
            islast=True,
            ishistory=True,
            isrealtime=False,
            isnew=False,
            isconfirmed=True,
        )

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
        del namespace
        child.indicator_state = {}
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
