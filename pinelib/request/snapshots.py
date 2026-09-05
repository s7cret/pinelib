"""Read-only, content-addressed datasets for compiled historical requests.

The caller supplies canonical bars and explicit instrument metadata. This
provider neither fetches the network nor resamples/relables the chart series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from pinelib.errors import PL_REQUEST_DATA, PineRuntimeError
from pinelib.request.models import (
    CanonicalBar,
    CoverageMode,
    DataCoverage,
    DataFinality,
    DataSnapshot,
    GapsMode,
    LookaheadMode,
    RequestKind,
    RequestQuery,
    RevisionPolicy,
)
from pinelib.request.provider import (
    ProviderDescriptor,
    ProviderErrorKind,
    RequestProviderError,
)
from pinelib.runtime.metadata import InstrumentContext, TimeframeContext
from pinelib.state.checkpoint import is_canonical_sha256, sha


def normalized_period(value: str) -> str:
    tf = TimeframeContext.parse(value)
    return (
        str(tf.multiplier)
        + {
            "second": "S",
            "minute": "",
            "day": "D",
            "week": "W",
            "month": "M",
            "tick": "T",
        }[tf.unit]
    )


@dataclass(frozen=True, slots=True)
class RequestSource:
    instrument_id: str
    instrument: InstrumentContext
    market: str
    timeframe: str
    bars: tuple[CanonicalBar, ...]
    provenance_hash: str
    _content_hash: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not str or not value or value.strip() != value
                for value in (self.instrument_id, self.market)
            )
            or not is_canonical_sha256(self.provenance_hash)
            or not isinstance(self.instrument, InstrumentContext)
            or not isinstance(self.bars, tuple)
        ):
            raise PineRuntimeError(
                "request source identity is incomplete", code=PL_REQUEST_DATA
            )
        for name in ("mintick", "pointvalue", "mincontract"):
            value = getattr(self.instrument, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise PineRuntimeError(
                    "request source metadata must be finite and positive",
                    code=PL_REQUEST_DATA,
                )
        if normalized_period(self.timeframe) != self.timeframe:
            raise PineRuntimeError(
                "request source timeframe is not canonical", code=PL_REQUEST_DATA
            )
        previous = None
        for bar in self.bars:
            if not isinstance(bar, CanonicalBar):
                raise PineRuntimeError(
                    "request source needs canonical bars", code=PL_REQUEST_DATA
                )
            for name in ("open", "high", "low", "close", "volume"):
                raw = getattr(bar, name)
                if (
                    raw is None
                    or not math.isfinite(float(raw))
                    or (Decimal(raw) != 0 and float(raw) == 0)
                ):
                    raise PineRuntimeError(
                        "request bar is outside the finite runtime range",
                        code=PL_REQUEST_DATA,
                    )
            if Decimal(bar.volume) < 0:
                raise PineRuntimeError(
                    "request volume cannot be negative", code=PL_REQUEST_DATA
                )
            if (
                bar.instrument_id != self.instrument_id
                or bar.timeframe != self.timeframe
                or bar.finality != DataFinality.FINAL
                or bar.revision != 0
            ):
                raise PineRuntimeError(
                    "request source needs matching original final bars",
                    code=PL_REQUEST_DATA,
                )
            if previous is not None and bar.open_time_ms < previous:
                raise PineRuntimeError(
                    "request source bars overlap or are unordered", code=PL_REQUEST_DATA
                )
            previous = bar.close_time_ms
        object.__setattr__(
            self,
            "_content_hash",
            sha(
                {
                    "instrument_id": self.instrument_id,
                    "instrument": self.instrument.identity(),
                    "market": self.market,
                    "timeframe": self.timeframe,
                    "provenance_hash": self.provenance_hash,
                    "bars": [bar.identity() for bar in self.bars],
                }
            ),
        )

    @property
    def content_hash(self) -> str:
        return self._content_hash


class SnapshotRequestProvider:
    """Content-bound preloads. Unavailable data is not proof of an invalid ticker."""

    def __init__(
        self, sources: tuple[RequestSource, ...], *, max_bars: int = 250_000
    ) -> None:
        if not sources or type(max_bars) is not int or max_bars <= 0:
            raise PineRuntimeError(
                "bounded request sources are required", code=PL_REQUEST_DATA
            )
        by_key, by_hash = {}, {}
        for source in sources:
            if len(source.bars) > max_bars:
                raise PineRuntimeError(
                    "request source exceeds the bar limit", code=PL_REQUEST_DATA
                )
            # Both names are explicit source metadata, not inferred ticker aliases.
            # A canonical ID exposed as syminfo.tickerid by a host must resolve
            # the same data as the declared venue ticker ID. Cross-source alias
            # collisions fail rather than depending on source insertion order.
            for name in {source.instrument_id, source.instrument.tickerid}:
                key = (name, source.timeframe)
                if key in by_key:
                    raise PineRuntimeError(
                        "duplicate or ambiguous request source identity",
                        code=PL_REQUEST_DATA,
                    )
                by_key[key] = source
            by_hash[source.content_hash] = source
        self._sources = MappingProxyType(by_key)
        self._by_hash = MappingProxyType(by_hash)
        self._descriptor = ProviderDescriptor(
            "snapshots:" + sha(sorted(by_hash)),
            "openpine.marketdata.v2",
            (
                "request.security",
                "request.security_lower_tf",
                "request.dynamic",
                "request.nested",
            ),
            max_bars,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def source(self, tickerid: str, timeframe: str) -> RequestSource:
        key = (tickerid, normalized_period(timeframe))
        source = self._sources.get(key)
        if source is None:
            raise RequestProviderError(
                ProviderErrorKind.UNAVAILABLE_DATASET,
                f"request dataset is not preloaded: {key!r}",
            )
        return source

    def query(
        self,
        source: RequestSource,
        *,
        kind: RequestKind,
        expression_id: str,
        call_site_id: str,
        currency: str | None,
        gaps: GapsMode,
        lookahead: LookaheadMode,
        calc_bars_count: int | None,
        pine_version: int,
        dynamic: bool,
    ) -> RequestQuery:
        if currency is not None and currency != source.instrument.currency:
            raise RequestProviderError(
                ProviderErrorKind.UNAVAILABLE_DATASET,
                "request currency conversion requires an admitted rate dataset",
            )
        if calc_bars_count is not None and (
            type(calc_bars_count) is not int or calc_bars_count <= 0
        ):
            raise PineRuntimeError(
                "calc_bars_count must be a positive integer", code=PL_REQUEST_DATA
            )
        return RequestQuery(
            kind,
            source.instrument_id,
            source.instrument.ticker,
            source.instrument.prefix,
            source.market,
            source.timeframe,
            call_site_id,
            expression_id,
            currency,
            gaps,
            lookahead,
            calc_bars_count,
            self.descriptor.provider_id,
            source.content_hash,
            RevisionPolicy.EXACT,
            CoverageMode.REQUIRE_COMPLETE,
            pine_version,
            dynamic,
        )

    def fetch(self, query: RequestQuery) -> DataSnapshot:
        source = self._by_hash.get(query.snapshot_id)
        if (
            source is None
            or source.instrument_id != query.instrument_id
            or source.timeframe != query.timeframe
            or query.provider_id != self.descriptor.provider_id
            or query.symbol != source.instrument.ticker
            or query.exchange != source.instrument.prefix
            or query.market != source.market
            or query.currency not in (None, source.instrument.currency)
        ):
            raise RequestProviderError(
                ProviderErrorKind.REVISION, "request source identity changed"
            )
        bars = (
            source.bars
            if query.calc_bars_count is None
            else source.bars[-query.calc_bars_count :]
        )
        return DataSnapshot.seal(
            provider_id=self.descriptor.provider_id,
            snapshot_id=query.snapshot_id,
            query=query,
            revision=0,
            finality=DataFinality.FINAL,
            coverage=DataCoverage(
                bars[0].open_time_ms if bars else None,
                bars[-1].close_time_ms if bars else None,
                True,
                len(bars),
            ),
            bars=bars,
        )
