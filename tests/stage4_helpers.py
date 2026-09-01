from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from pinelib.request import (
    CanonicalBar,
    CoverageMode,
    DataCoverage,
    DataFinality,
    DataSnapshot,
    GapsMode,
    LookaheadMode,
    ProviderDescriptor,
    ProviderErrorKind,
    RequestKind,
    RequestProviderError,
    RequestQuery,
    RevisionPolicy,
    SnapshotMode,
)
from pinelib.runtime import (
    RequestPolicy,
    ResourcePolicy,
    RuntimePolicies,
    RuntimeSession,
    TimeframeContext,
)
from tests.stage3_helpers import language


class MemoryProvider:
    def __init__(
        self,
        snapshots: dict[str, object] | None = None,
        *,
        provider_id: str = "provider:test",
        capabilities: tuple[str, ...] = (
            "request.dynamic",
            "request.nested",
            "request.security",
            "request.security_lower_tf",
        ),
        max_bars_per_query: int = 10_000,
    ) -> None:
        self.descriptor = ProviderDescriptor(
            provider_id,
            "openpine.marketdata.v2",
            capabilities,
            max_bars_per_query,
        )
        self.snapshots = dict(snapshots or {})
        self.calls: list[RequestQuery] = []

    def fetch(self, query: RequestQuery) -> DataSnapshot:
        self.calls.append(query)
        result = self.snapshots.get(query.snapshot_id)
        if result is None:
            raise RequestProviderError(
                ProviderErrorKind.UNAVAILABLE_DATASET,
                "snapshot is not available",
            )
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            result = result(query)
        if not isinstance(result, DataSnapshot):
            raise TypeError("test provider result is not a DataSnapshot")
        return result


def query(
    *,
    kind: RequestKind = RequestKind.SECURITY,
    timeframe: str = "60",
    snapshot_id: str = "snapshot:1",
    expression_context_id: str = "call:request",
    expression_id: str = "expr:close",
    gaps: GapsMode = GapsMode.OFF,
    lookahead: LookaheadMode = LookaheadMode.OFF,
    calc_bars_count: int | None = None,
    version: int = 6,
    dynamic: bool = False,
    coverage_mode: CoverageMode = CoverageMode.REQUIRE_COMPLETE,
    parent_context_hash: str | None = None,
    provider_id: str = "provider:test",
    instrument_id: str = "instrument:BTCUSDT",
) -> RequestQuery:
    return RequestQuery(
        kind,
        instrument_id,
        "BTCUSDT",
        "BINANCE",
        "spot",
        timeframe,
        expression_context_id,
        expression_id,
        "USDT",
        gaps,
        lookahead,
        calc_bars_count,
        provider_id,
        snapshot_id,
        RevisionPolicy.EXACT,
        coverage_mode,
        version,
        dynamic,
        parent_context_hash,
    )


def bars(
    request_query: RequestQuery,
    values: Iterable[float],
    *,
    start_ms: int = 0,
    finalities: Iterable[DataFinality] | None = None,
    revision: int = 0,
) -> tuple[CanonicalBar, ...]:
    seconds = TimeframeContext.parse(request_query.timeframe).seconds
    if seconds is None:
        raise ValueError("test helper requires fixed-duration timeframe")
    duration = seconds * 1000
    values_tuple = tuple(values)
    finality_tuple = (
        tuple(finalities)
        if finalities is not None
        else (DataFinality.FINAL,) * len(values_tuple)
    )
    if len(finality_tuple) != len(values_tuple):
        raise ValueError("finality count mismatch")
    result = []
    for index, (value, finality) in enumerate(
        zip(values_tuple, finality_tuple, strict=True)
    ):
        opening = start_ms + index * duration
        text = str(value)
        result.append(
            CanonicalBar(
                request_query.instrument_id,
                request_query.timeframe,
                opening,
                opening + duration,
                text,
                str(value + 1),
                str(value - 1),
                text,
                "100",
                finality,
                revision,
                "session:24x7",
            )
        )
    return tuple(result)


def snapshot(
    request_query: RequestQuery,
    source_bars: tuple[CanonicalBar, ...],
    *,
    complete: bool = True,
    revision: int = 0,
    mode: SnapshotMode = SnapshotMode.FULL,
    parent_snapshot_hash: str | None = None,
) -> DataSnapshot:
    coverage = DataCoverage(
        None if not source_bars else source_bars[0].open_time_ms,
        None if not source_bars else source_bars[-1].close_time_ms,
        complete,
        len(source_bars),
    )
    finality = (
        DataFinality.FINAL
        if all(item.finality == DataFinality.FINAL for item in source_bars)
        else DataFinality.DEVELOPING
    )
    return DataSnapshot.seal(
        provider_id=request_query.provider_id,
        snapshot_id=request_query.snapshot_id,
        query=request_query,
        revision=revision,
        finality=finality,
        coverage=coverage,
        bars=source_bars,
        mode=mode,
        parent_snapshot_hash=parent_snapshot_hash,
    )


def provider_for(
    request_query: RequestQuery, source_bars: tuple[CanonicalBar, ...], **kwargs
) -> MemoryProvider:
    sealed = snapshot(request_query, source_bars, **kwargs)
    return MemoryProvider(
        {request_query.snapshot_id: sealed}, provider_id=request_query.provider_id
    )


def request_session(
    provider: MemoryProvider,
    *,
    version: int = 6,
    request_policy: RequestPolicy | None = None,
    resource_policy: ResourcePolicy | None = None,
) -> RuntimeSession:
    policies = RuntimePolicies(
        request=RequestPolicy() if request_policy is None else request_policy,
        resource=ResourcePolicy() if resource_policy is None else resource_policy,
    )
    return RuntimeSession(language(version), policies, request_provider=provider)


def replace_query(request_query: RequestQuery, **changes: object) -> RequestQuery:
    return replace(request_query, **changes)
