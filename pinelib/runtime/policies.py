from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pinelib.errors import PL_REQUEST_POLICY, PL_RESOURCE_LIMIT, PineRuntimeError

DynamicRequestMode = Literal["version_default", "enabled", "disabled"]
NestedRequestMode = Literal["enabled", "disabled"]


def _positive(name: str, value: int) -> None:
    if type(value) is not int or value <= 0:
        raise PineRuntimeError(
            f"{name} must be a positive int",
            code=PL_RESOURCE_LIMIT,
            details={"field": name, "value": value},
        )


@dataclass(frozen=True, slots=True)
class RealtimePolicy:
    require_explicit_ticks: bool = True
    max_recalculations_per_bar: int = 64

    def __post_init__(self) -> None:
        _positive("max_recalculations_per_bar", self.max_recalculations_per_bar)


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    """Version-bound request policy supplied by the generated artifact.

    ``version_default`` means dynamic requests are disabled through Pine v5 and
    enabled in Pine v6.  No runtime guess is made from argument Python types.
    """

    dynamic_requests: DynamicRequestMode = "version_default"
    nested_requests: NestedRequestMode = "disabled"
    require_historical_discovery: bool = True
    allow_developing_realtime: bool = True

    def __post_init__(self) -> None:
        if self.dynamic_requests not in {"version_default", "enabled", "disabled"}:
            raise PineRuntimeError(
                "invalid dynamic request policy", code=PL_REQUEST_POLICY
            )
        if self.nested_requests not in {"enabled", "disabled"}:
            raise PineRuntimeError(
                "invalid nested request policy", code=PL_REQUEST_POLICY
            )

    def dynamic_enabled(self, pine_version: int) -> bool:
        if self.dynamic_requests == "enabled":
            return True
        if self.dynamic_requests == "disabled":
            return False
        return pine_version >= 6

    @property
    def nested_enabled(self) -> bool:
        return self.nested_requests == "enabled"


@dataclass(frozen=True, slots=True)
class TimePolicy:
    tzdata_version: Literal["2026.2"] = "2026.2"
    timezone_backend: Literal["tzdata-package"] = "tzdata-package"


@dataclass(frozen=True, slots=True)
class NumericPolicy:
    representation: Literal["binary64"] = "binary64"
    contract_encoding: Literal["shortest-round-trip-decimal"] = (
        "shortest-round-trip-decimal"
    )


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    max_series: int = 10_000
    max_state_slots: int = 10_000
    max_checkpoint_bytes: int = 16 * 1024 * 1024
    max_reference_objects: int = 10_000
    max_collection_elements: int = 100_000
    max_visual_events: int = 100_000
    max_alert_events: int = 100_000
    max_request_datasets: int = 64
    max_request_depth: int = 4
    max_request_bars: int = 250_000
    max_intrabars_per_bar: int = 100_000
    max_request_state_bytes: int = 16 * 1024 * 1024
    max_request_cache_bytes: int = 128 * 1024 * 1024
    max_request_evaluations_per_callback: int = 500_000

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _positive(field_name, getattr(self, field_name))


@dataclass(frozen=True, slots=True)
class RuntimePolicies:
    realtime: RealtimePolicy = RealtimePolicy()
    request: RequestPolicy = RequestPolicy()
    time: TimePolicy = TimePolicy()
    numeric: NumericPolicy = NumericPolicy()
    resource: ResourcePolicy = ResourcePolicy()

    def identity(self) -> dict[str, object]:
        return {
            "realtime": {
                "require_explicit_ticks": self.realtime.require_explicit_ticks,
                "max_recalculations_per_bar": self.realtime.max_recalculations_per_bar,
            },
            "request": {
                "dynamic_requests": self.request.dynamic_requests,
                "nested_requests": self.request.nested_requests,
                "require_historical_discovery": self.request.require_historical_discovery,
                "allow_developing_realtime": self.request.allow_developing_realtime,
            },
            "time": {
                "tzdata_version": self.time.tzdata_version,
                "timezone_backend": self.time.timezone_backend,
            },
            "numeric": {
                "representation": self.numeric.representation,
                "contract_encoding": self.numeric.contract_encoding,
            },
            "resource": {
                field_name: getattr(self.resource, field_name)
                for field_name in self.resource.__dataclass_fields__
            },
        }
