from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pinelib.errors import (
    PL_REQUEST_COVERAGE,
    PL_REQUEST_DATA,
    PL_REQUEST_INVALID_SYMBOL,
    PL_REQUEST_PROVIDER,
    PL_REQUEST_REVISION,
    PL_REQUEST_TRANSPORT,
    PL_REQUEST_UNAVAILABLE,
    PineRuntimeError,
)
from pinelib.request.models import DataSnapshot, RequestQuery
from pinelib.state.checkpoint import sha


class ProviderErrorKind(StrEnum):
    INVALID_SYMBOL = "INVALID_SYMBOL"
    UNAVAILABLE_DATASET = "UNAVAILABLE_DATASET"
    INCOMPLETE_COVERAGE = "INCOMPLETE_COVERAGE"
    TRANSPORT = "TRANSPORT"
    SCHEMA = "SCHEMA"
    REVISION = "REVISION"


_ERROR_CODES = {
    ProviderErrorKind.INVALID_SYMBOL: PL_REQUEST_INVALID_SYMBOL,
    ProviderErrorKind.UNAVAILABLE_DATASET: PL_REQUEST_UNAVAILABLE,
    ProviderErrorKind.INCOMPLETE_COVERAGE: PL_REQUEST_COVERAGE,
    ProviderErrorKind.TRANSPORT: PL_REQUEST_TRANSPORT,
    ProviderErrorKind.SCHEMA: PL_REQUEST_DATA,
    ProviderErrorKind.REVISION: PL_REQUEST_REVISION,
}


class RequestProviderError(PineRuntimeError):
    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        try:
            normalized = ProviderErrorKind(kind)
        except ValueError as error:
            raise PineRuntimeError(
                "unknown provider error kind", code=PL_REQUEST_PROVIDER
            ) from error
        super().__init__(message, code=_ERROR_CODES[normalized], details=details)
        self.kind = normalized


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    contract_version: str
    capabilities: tuple[str, ...]
    max_bars_per_query: int

    def __post_init__(self) -> None:
        if not self.provider_id or self.provider_id.strip() != self.provider_id:
            raise PineRuntimeError("provider_id is invalid", code=PL_REQUEST_PROVIDER)
        if self.contract_version != "openpine.marketdata.v2":
            raise PineRuntimeError(
                "provider contract version mismatch", code=PL_REQUEST_PROVIDER
            )
        if type(self.max_bars_per_query) is not int or self.max_bars_per_query <= 0:
            raise PineRuntimeError(
                "provider max_bars_per_query is invalid", code=PL_REQUEST_PROVIDER
            )
        normalized = tuple(sorted(set(self.capabilities)))
        if not normalized or any(
            type(item) is not str or not item or item.strip() != item
            for item in normalized
        ):
            raise PineRuntimeError(
                "provider capabilities are invalid", code=PL_REQUEST_PROVIDER
            )
        object.__setattr__(self, "capabilities", normalized)

    def identity(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "contract_version": self.contract_version,
            "capabilities": list(self.capabilities),
            "max_bars_per_query": self.max_bars_per_query,
        }

    @property
    def content_hash(self) -> str:
        return sha(self.identity())

    def require(self, capability: str) -> None:
        if capability not in self.capabilities:
            raise PineRuntimeError(
                f"provider capability is not admitted: {capability}",
                code=PL_REQUEST_PROVIDER,
                details={"provider_id": self.provider_id, "capability": capability},
            )


@runtime_checkable
class RequestDataProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def fetch(self, query: RequestQuery) -> DataSnapshot: ...


def validate_provider(provider: object | None) -> ProviderDescriptor | None:
    if provider is None:
        return None
    descriptor = getattr(provider, "descriptor", None)
    fetch = getattr(provider, "fetch", None)
    if not isinstance(descriptor, ProviderDescriptor) or not callable(fetch):
        raise PineRuntimeError(
            "request provider does not implement the exact protocol",
            code=PL_REQUEST_PROVIDER,
        )
    return descriptor


def fetch_snapshot(provider: RequestDataProvider, query: RequestQuery) -> DataSnapshot:
    try:
        snapshot = provider.fetch(query)
    except RequestProviderError:
        raise
    except Exception as error:
        raise RequestProviderError(
            ProviderErrorKind.TRANSPORT,
            "request provider failed",
            details={
                "provider_id": query.provider_id,
                "error_type": type(error).__name__,
            },
        ) from error
    if not isinstance(snapshot, DataSnapshot):
        raise RequestProviderError(
            ProviderErrorKind.SCHEMA,
            "request provider returned a non-canonical snapshot",
            details={"provider_id": query.provider_id},
        )
    return snapshot
