"""Validated immutable wrapper for ``openpine.execution_context.v1``."""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

from openpine_contracts import validate_payload, verify_content_hash

from pinelib.core.types import SymbolInfo, TimeframeInfo
from pinelib.version import PACKAGE_VERSION

SCHEMA_ID = "openpine.execution_context.v1"


class ExecutionContext(Mapping[str, Any]):
    """A detached, schema-validated and content-hash-verified execution context."""

    __slots__ = ("_payload",)

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError("execution_context must be a mapping")
        detached = copy.deepcopy(dict(payload))
        validate_payload(SCHEMA_ID, detached)
        if not verify_content_hash(detached):
            raise ValueError("execution_context content_hash does not match its payload")
        pinelib_wheels = [
            identity for identity in detached["wheel_identities"] if identity["name"] == "pinelib"
        ]
        if len(pinelib_wheels) != 1 or pinelib_wheels[0]["version"] != PACKAGE_VERSION:
            raise ValueError(
                "execution_context pinelib wheel version does not match the running package"
            )
        self._payload = detached

    @classmethod
    def coerce(cls, value: ExecutionContext | Mapping[str, Any]) -> ExecutionContext:
        if isinstance(value, cls):
            return value
        return cls(value)

    def __getitem__(self, key: str) -> Any:
        return copy.deepcopy(self._payload[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible payload."""

        return copy.deepcopy(self._payload)

    @property
    def content_hash(self) -> str:
        return str(self._payload["content_hash"])

    @property
    def source_hash(self) -> str:
        return str(self._payload["source_hash"])

    @property
    def pinelib_commit(self) -> str:
        commits = self._payload["producer_commits"]
        assert isinstance(commits, dict)
        return str(commits["pinelib"])

    def to_symbol_info(self) -> SymbolInfo:
        """Build Pine ``syminfo`` solely from admitted instrument metadata."""

        return SymbolInfo(
            tickerid=str(self._payload["instrument_id"]),
            timezone=str(self._payload["timezone"]),
            session=str(self._payload["session_policy"]),
            mintick=float(Decimal(str(self._payload["mintick"]))),
            exchange=str(self._payload["exchange"]),
            type=str(self._payload["market"]),
            currency=str(self._payload["currency"]),
            pointvalue=float(Decimal(str(self._payload["pointvalue"]))),
        )

    def assert_runtime_identity(
        self,
        symbol_info: SymbolInfo,
        timeframe: TimeframeInfo,
    ) -> None:
        """Reject a runtime whose symbol/rules differ from admission."""

        expected = self.to_symbol_info()
        mismatches: list[str] = []
        for field in (
            "tickerid",
            "timezone",
            "session",
            "exchange",
            "type",
            "currency",
        ):
            if getattr(symbol_info, field) != getattr(expected, field):
                mismatches.append(field)
        if Decimal(str(symbol_info.mintick)) != Decimal(str(expected.mintick)):
            mismatches.append("mintick")
        if Decimal(str(symbol_info.pointvalue)) != Decimal(str(expected.pointvalue)):
            mismatches.append("pointvalue")
        if symbol_info.ticker != str(self._payload["symbol"]):
            mismatches.append("symbol")
        if timeframe.value != str(self._payload["timeframe"]):
            mismatches.append("timeframe")
        if mismatches:
            raise ValueError(
                "strict runtime instrument identity does not match execution_context: "
                + ", ".join(sorted(set(mismatches)))
            )
