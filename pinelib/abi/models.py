from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TargetStatus(StrEnum):
    SUPPORTED_PURE = "SUPPORTED_PURE"
    SUPPORTED_STATEFUL = "SUPPORTED_STATEFUL"
    SUPPORTED_CONTEXT = "SUPPORTED_CONTEXT"
    UNSUPPORTED_FAIL_CLOSED = "UNSUPPORTED_FAIL_CLOSED"
    NOT_APPLICABLE_VERSION = "NOT_APPLICABLE_VERSION"


@dataclass(frozen=True, slots=True)
class CatalogRow:
    symbol_id: str
    overload_id: str
    call_form: str
    pine_versions: tuple[int, ...]
    status: TargetStatus
    abi_callable: str | None
    return_type: str
    evaluation_mode: str
    state_model: str
    capabilities: tuple[str, ...]
    diagnostic: str | None = None
    tuple_arity: int = 0
