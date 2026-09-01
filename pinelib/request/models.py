from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType

from pinelib.core.values import is_na, na
from pinelib.errors import (
    PL_REQUEST_DATA,
    PL_REQUEST_IDENTITY,
    PL_REQUEST_RESULT_SHAPE,
    PineRuntimeError,
)
from pinelib.runtime.metadata import TimeframeContext
from pinelib.state.checkpoint import (
    canonical_json,
    from_portable,
    is_canonical_sha256,
    sha,
    to_portable,
)


class RequestKind(StrEnum):
    SECURITY = "request.security"
    SECURITY_LOWER_TF = "request.security_lower_tf"


class DataFinality(StrEnum):
    FINAL = "FINAL"
    DEVELOPING = "DEVELOPING"


class SnapshotMode(StrEnum):
    FULL = "FULL"
    APPEND = "APPEND"


class GapsMode(StrEnum):
    OFF = "gaps_off"
    ON = "gaps_on"


class LookaheadMode(StrEnum):
    OFF = "lookahead_off"
    ON = "lookahead_on"


class RevisionPolicy(StrEnum):
    EXACT = "EXACT"


class CoverageMode(StrEnum):
    REQUIRE_COMPLETE = "REQUIRE_COMPLETE"
    ALLOW_PARTIAL = "ALLOW_PARTIAL"


class ResultKind(StrEnum):
    SCALAR = "scalar"
    TUPLE = "tuple"
    ARRAY = "array"
    UDT = "udt"
    MAP = "map"


class DatasetStatus(StrEnum):
    READY = "READY"
    INVALID_SYMBOL = "INVALID_SYMBOL"


def _require_canonical_payload(
    original: object,
    normalized: object,
    *,
    message: str,
    code: str,
) -> None:
    if canonical_json(normalized) != canonical_json(original):
        raise PineRuntimeError(message, code=code)


def _require_text(name: str, value: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise PineRuntimeError(
            f"{name} must be a non-empty canonical string",
            code=PL_REQUEST_IDENTITY,
            details={"field": name},
        )


def _hash(value: str, name: str) -> None:
    if not is_canonical_sha256(value):
        raise PineRuntimeError(
            f"{name} must be a canonical sha256",
            code=PL_REQUEST_IDENTITY,
            details={"field": name},
        )


def _decimal_text(value: str, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise PineRuntimeError(f"{name} must be a decimal string", code=PL_REQUEST_DATA)
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise PineRuntimeError(
            f"{name} is not a valid decimal", code=PL_REQUEST_DATA
        ) from error
    if not number.is_finite():
        raise PineRuntimeError(f"{name} must be finite", code=PL_REQUEST_DATA)
    if number.is_zero():
        return "-0" if number.is_signed() else "0"
    text = format(number.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ResultShape:
    kind: ResultKind
    type_name: str = "object"
    items: tuple[ResultShape, ...] = ()
    fields: tuple[tuple[str, ResultShape], ...] = ()
    nullable: bool = True

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "kind", ResultKind(self.kind))
        except ValueError as error:
            raise PineRuntimeError(
                "unknown request result shape", code=PL_REQUEST_RESULT_SHAPE
            ) from error
        _require_text("result type_name", self.type_name)
        if type(self.nullable) is not bool:
            raise PineRuntimeError(
                "result nullable must be a bool", code=PL_REQUEST_RESULT_SHAPE
            )
        if self.kind == ResultKind.SCALAR:
            if self.items or self.fields:
                raise PineRuntimeError(
                    "scalar result shape cannot contain children",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
        elif self.kind == ResultKind.TUPLE:
            if not self.items or self.fields:
                raise PineRuntimeError(
                    "tuple result shape requires item descriptors",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
        elif self.kind == ResultKind.ARRAY:
            if len(self.items) != 1 or self.fields:
                raise PineRuntimeError(
                    "array result shape requires one element descriptor",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
        elif self.kind == ResultKind.UDT:
            names = tuple(name for name, _ in self.fields)
            if not names or self.items or len(set(names)) != len(names):
                raise PineRuntimeError(
                    "UDT result shape requires unique fields",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
            for name in names:
                _require_text("UDT field", name)
        elif self.kind == ResultKind.MAP and (len(self.items) != 2 or self.fields):
            raise PineRuntimeError(
                "map result shape requires key and value descriptors",
                code=PL_REQUEST_RESULT_SHAPE,
            )

    @classmethod
    def scalar(cls, type_name: str = "object", *, nullable: bool = True) -> ResultShape:
        return cls(ResultKind.SCALAR, type_name, nullable=nullable)

    @classmethod
    def tuple_of(cls, *items: ResultShape, nullable: bool = True) -> ResultShape:
        return cls(ResultKind.TUPLE, "tuple", tuple(items), nullable=nullable)

    @classmethod
    def array_of(cls, item: ResultShape, *, nullable: bool = True) -> ResultShape:
        return cls(ResultKind.ARRAY, "array", (item,), nullable=nullable)

    @classmethod
    def udt(
        cls,
        type_name: str,
        fields: Mapping[str, ResultShape],
        *,
        nullable: bool = True,
    ) -> ResultShape:
        return cls(
            ResultKind.UDT, type_name, fields=tuple(fields.items()), nullable=nullable
        )

    @classmethod
    def map_of(
        cls, key: ResultShape, value: ResultShape, *, nullable: bool = True
    ) -> ResultShape:
        return cls(ResultKind.MAP, "map", (key, value), nullable=nullable)

    def identity(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "type_name": self.type_name,
            "items": [item.identity() for item in self.items],
            "fields": [
                {"name": name, "shape": shape.identity()} for name, shape in self.fields
            ],
            "nullable": self.nullable,
        }

    @property
    def content_hash(self) -> str:
        return sha(self.identity())

    def validate(self, value: object) -> object:
        """Validate and return a detached portable representation."""

        if is_na(value):
            if not self.nullable:
                raise PineRuntimeError(
                    "request result cannot be na", code=PL_REQUEST_RESULT_SHAPE
                )
            return to_portable(na)
        if value is None:
            raise PineRuntimeError(
                "Python None is not an implicit Pine value",
                code=PL_REQUEST_RESULT_SHAPE,
            )
        if self.kind == ResultKind.SCALAR:
            return to_portable(self._validate_scalar(value))
        if self.kind == ResultKind.TUPLE:
            if not isinstance(value, (tuple, list)) or len(value) != len(self.items):
                raise PineRuntimeError(
                    "request tuple result arity mismatch",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
            return [
                shape.validate(item)
                for shape, item in zip(self.items, value, strict=True)
            ]
        if self.kind == ResultKind.ARRAY:
            if not isinstance(value, (tuple, list)):
                raise PineRuntimeError(
                    "request array result must be a sequence",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
            return [self.items[0].validate(item) for item in value]
        if self.kind == ResultKind.UDT:
            if not isinstance(value, Mapping):
                raise PineRuntimeError(
                    "request UDT result must be a mapping",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
            expected = {name for name, _ in self.fields}
            if set(value) != expected:
                raise PineRuntimeError(
                    "request UDT field mismatch", code=PL_REQUEST_RESULT_SHAPE
                )
            return {name: shape.validate(value[name]) for name, shape in self.fields}
        if not isinstance(value, Mapping):
            raise PineRuntimeError(
                "request map result must be a mapping",
                code=PL_REQUEST_RESULT_SHAPE,
            )
        key_shape, value_shape = self.items
        encoded = [
            [key_shape.validate(key), value_shape.validate(item)]
            for key, item in value.items()
        ]
        encoded.sort(key=lambda pair: canonical_json(pair[0]))
        return encoded

    def restore(self, value: object) -> object:
        decoded = from_portable(value)
        if self.kind == ResultKind.MAP and not is_na(decoded):
            if not isinstance(decoded, list):
                raise PineRuntimeError(
                    "stored request map result is invalid",
                    code=PL_REQUEST_RESULT_SHAPE,
                )
            key_shape, value_shape = self.items
            restored: dict[object, object] = {}
            for pair in decoded:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise PineRuntimeError(
                        "stored request map entry is invalid",
                        code=PL_REQUEST_RESULT_SHAPE,
                    )
                key = key_shape.restore(pair[0])
                item = value_shape.restore(pair[1])
                restored[_freeze(key)] = _freeze(item)
            return MappingProxyType(restored)
        validated = self.validate(decoded)
        if canonical_json(validated) != canonical_json(value):
            raise PineRuntimeError(
                "stored request result is not canonical for its shape",
                code=PL_REQUEST_RESULT_SHAPE,
            )
        return _freeze(from_portable(validated))

    def _validate_scalar(self, value: object) -> object:
        name = self.type_name
        if name in {"object", "any"}:
            to_portable(value)
            return value
        if name == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PineRuntimeError(
                    "expected float result", code=PL_REQUEST_RESULT_SHAPE
                )
            number = float(value)
            to_portable(number)
            return number
        if name == "int":
            if type(value) is not int:
                raise PineRuntimeError(
                    "expected int result", code=PL_REQUEST_RESULT_SHAPE
                )
            return value
        if name == "bool":
            if type(value) is not bool:
                raise PineRuntimeError(
                    "expected bool result", code=PL_REQUEST_RESULT_SHAPE
                )
            return value
        if name in {"string", "color", "source"}:
            if type(value) is not str:
                raise PineRuntimeError(
                    "expected string result", code=PL_REQUEST_RESULT_SHAPE
                )
            return value
        to_portable(value)
        return value

    @classmethod
    def from_dict(cls, data: object) -> ResultShape:
        if not isinstance(data, dict):
            raise PineRuntimeError(
                "result shape must be an object", code=PL_REQUEST_RESULT_SHAPE
            )
        required = {"kind", "type_name", "items", "fields", "nullable"}
        if (
            set(data) != required
            or not isinstance(data["items"], list)
            or not isinstance(data["fields"], list)
        ):
            raise PineRuntimeError(
                "result shape schema mismatch", code=PL_REQUEST_RESULT_SHAPE
            )
        fields: list[tuple[str, ResultShape]] = []
        for row in data["fields"]:
            if not isinstance(row, dict) or set(row) != {"name", "shape"}:
                raise PineRuntimeError(
                    "result field schema mismatch", code=PL_REQUEST_RESULT_SHAPE
                )
            fields.append((str(row["name"]), cls.from_dict(row["shape"])))
        restored = cls(
            ResultKind(str(data["kind"])),
            str(data["type_name"]),
            tuple(cls.from_dict(item) for item in data["items"]),
            tuple(fields),
            data["nullable"],
        )
        _require_canonical_payload(
            data,
            restored.identity(),
            message="result shape is not canonical",
            code=PL_REQUEST_RESULT_SHAPE,
        )
        return restored


@dataclass(frozen=True, slots=True)
class RequestQuery:
    kind: RequestKind
    instrument_id: str
    symbol: str
    exchange: str
    market: str
    timeframe: str
    expression_context_id: str
    expression_id: str
    currency: str | None
    gaps: GapsMode
    lookahead: LookaheadMode
    calc_bars_count: int | None
    provider_id: str
    snapshot_id: str
    revision_policy: RevisionPolicy
    coverage_mode: CoverageMode
    pine_version: int
    dynamic: bool = False
    parent_context_hash: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "kind", RequestKind(self.kind))
            object.__setattr__(self, "gaps", GapsMode(self.gaps))
            object.__setattr__(self, "lookahead", LookaheadMode(self.lookahead))
            object.__setattr__(
                self, "revision_policy", RevisionPolicy(self.revision_policy)
            )
            object.__setattr__(self, "coverage_mode", CoverageMode(self.coverage_mode))
        except ValueError as error:
            raise PineRuntimeError(
                "invalid request query enum", code=PL_REQUEST_DATA
            ) from error
        for name in (
            "instrument_id",
            "symbol",
            "exchange",
            "market",
            "timeframe",
            "expression_context_id",
            "expression_id",
            "provider_id",
            "snapshot_id",
        ):
            _require_text(name, getattr(self, name))
        if self.currency is not None:
            _require_text("currency", self.currency)
        if self.pine_version not in {1, 2, 3, 4, 5, 6}:
            raise PineRuntimeError(
                "invalid query Pine version", code=PL_REQUEST_IDENTITY
            )
        if self.calc_bars_count is not None and (
            type(self.calc_bars_count) is not int or self.calc_bars_count < 0
        ):
            raise PineRuntimeError(
                "calc_bars_count must be nonnegative", code=PL_REQUEST_DATA
            )
        if self.parent_context_hash is not None:
            _hash(self.parent_context_hash, "parent_context_hash")
        TimeframeContext.parse(self.timeframe)

    @property
    def timeframe_seconds(self) -> int:
        seconds = TimeframeContext.parse(self.timeframe).seconds
        if seconds is None:
            raise PineRuntimeError(
                "tick or calendar timeframe has no fixed second duration",
                code=PL_REQUEST_DATA,
            )
        return seconds

    def identity(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "market": self.market,
            "timeframe": self.timeframe,
            "expression_context_id": self.expression_context_id,
            "expression_id": self.expression_id,
            "currency": self.currency,
            "gaps": self.gaps.value,
            "lookahead": self.lookahead.value,
            "calc_bars_count": self.calc_bars_count,
            "provider_id": self.provider_id,
            "snapshot_id": self.snapshot_id,
            "revision_policy": self.revision_policy.value,
            "coverage_mode": self.coverage_mode.value,
            "pine_version": self.pine_version,
            "dynamic": self.dynamic,
            "parent_context_hash": self.parent_context_hash,
        }

    @property
    def content_hash(self) -> str:
        return sha(self.identity())

    @property
    def lineage_hash(self) -> str:
        body = self.identity()
        body.pop("snapshot_id")
        return sha(body)

    def discovery_identity(self, shape: ResultShape) -> str:
        return sha(
            {"query_hash": self.content_hash, "result_shape_hash": shape.content_hash}
        )

    def with_parent(self, parent_context_hash: str) -> RequestQuery:
        return replace(self, parent_context_hash=parent_context_hash)

    @classmethod
    def from_dict(cls, data: object) -> RequestQuery:
        if not isinstance(data, dict):
            raise PineRuntimeError(
                "request query must be an object", code=PL_REQUEST_DATA
            )
        required = {
            "kind",
            "instrument_id",
            "symbol",
            "exchange",
            "market",
            "timeframe",
            "expression_context_id",
            "expression_id",
            "currency",
            "gaps",
            "lookahead",
            "calc_bars_count",
            "provider_id",
            "snapshot_id",
            "revision_policy",
            "coverage_mode",
            "pine_version",
            "dynamic",
            "parent_context_hash",
        }
        if set(data) != required:
            raise PineRuntimeError(
                "request query schema mismatch", code=PL_REQUEST_DATA
            )
        restored = cls(
            RequestKind(str(data["kind"])),
            str(data["instrument_id"]),
            str(data["symbol"]),
            str(data["exchange"]),
            str(data["market"]),
            str(data["timeframe"]),
            str(data["expression_context_id"]),
            str(data["expression_id"]),
            None if data["currency"] is None else str(data["currency"]),
            GapsMode(str(data["gaps"])),
            LookaheadMode(str(data["lookahead"])),
            None if data["calc_bars_count"] is None else int(data["calc_bars_count"]),
            str(data["provider_id"]),
            str(data["snapshot_id"]),
            RevisionPolicy(str(data["revision_policy"])),
            CoverageMode(str(data["coverage_mode"])),
            int(data["pine_version"]),
            bool(data["dynamic"]),
            (
                None
                if data["parent_context_hash"] is None
                else str(data["parent_context_hash"])
            ),
        )
        if canonical_json(restored.identity()) != canonical_json(data):
            raise PineRuntimeError(
                "request query is not canonical", code=PL_REQUEST_DATA
            )
        return restored


@dataclass(frozen=True, slots=True)
class CanonicalBar:
    instrument_id: str
    timeframe: str
    open_time_ms: int
    close_time_ms: int
    open: str
    high: str
    low: str
    close: str
    volume: str | None
    finality: DataFinality
    revision: int
    session_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("instrument_id", self.instrument_id)
        _require_text("timeframe", self.timeframe)
        TimeframeContext.parse(self.timeframe)
        if (
            type(self.open_time_ms) is not int
            or type(self.close_time_ms) is not int
            or self.close_time_ms <= self.open_time_ms
        ):
            raise PineRuntimeError(
                "bar time boundaries are invalid", code=PL_REQUEST_DATA
            )
        if type(self.revision) is not int or self.revision < 0:
            raise PineRuntimeError("bar revision is invalid", code=PL_REQUEST_DATA)
        try:
            object.__setattr__(self, "finality", DataFinality(self.finality))
        except ValueError as error:
            raise PineRuntimeError(
                "bar finality is invalid", code=PL_REQUEST_DATA
            ) from error
        for field_name in ("open", "high", "low", "close"):
            object.__setattr__(
                self, field_name, _decimal_text(getattr(self, field_name), field_name)
            )
        if self.volume is not None:
            object.__setattr__(self, "volume", _decimal_text(self.volume, "volume"))
        if self.session_id is not None:
            _require_text("session_id", self.session_id)
        opening, high, low, closing = map(
            Decimal, (self.open, self.high, self.low, self.close)
        )
        if high < max(opening, low, closing) or low > min(opening, high, closing):
            raise PineRuntimeError("bar OHLC ordering is invalid", code=PL_REQUEST_DATA)

    def identity(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "open_time_ms": self.open_time_ms,
            "close_time_ms": self.close_time_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "finality": self.finality.value,
            "revision": self.revision,
            "session_id": self.session_id,
        }

    @property
    def content_hash(self) -> str:
        return sha(self.identity())

    def number(self, field: str) -> float:
        if field not in {"open", "high", "low", "close", "volume"}:
            raise PineRuntimeError(
                "unknown canonical bar numeric field", code=PL_REQUEST_DATA
            )
        value = getattr(self, field)
        if value is None:
            raise PineRuntimeError(
                "canonical bar field is unavailable", code=PL_REQUEST_DATA
            )
        return float(Decimal(value))

    @classmethod
    def from_dict(cls, data: object) -> CanonicalBar:
        if not isinstance(data, dict):
            raise PineRuntimeError(
                "canonical bar must be an object", code=PL_REQUEST_DATA
            )
        required = {
            "instrument_id",
            "timeframe",
            "open_time_ms",
            "close_time_ms",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "finality",
            "revision",
            "session_id",
        }
        if set(data) != required:
            raise PineRuntimeError(
                "canonical bar schema mismatch", code=PL_REQUEST_DATA
            )
        restored = cls(
            str(data["instrument_id"]),
            str(data["timeframe"]),
            int(data["open_time_ms"]),
            int(data["close_time_ms"]),
            str(data["open"]),
            str(data["high"]),
            str(data["low"]),
            str(data["close"]),
            None if data["volume"] is None else str(data["volume"]),
            DataFinality(str(data["finality"])),
            int(data["revision"]),
            None if data["session_id"] is None else str(data["session_id"]),
        )
        _require_canonical_payload(
            data,
            restored.identity(),
            message="canonical bar is not canonical",
            code=PL_REQUEST_DATA,
        )
        return restored


@dataclass(frozen=True, slots=True)
class DataCoverage:
    start_time_ms: int | None
    end_time_ms: int | None
    complete: bool
    bars_available: int

    def __post_init__(self) -> None:
        if type(self.complete) is not bool:
            raise PineRuntimeError(
                "coverage complete must be a bool", code=PL_REQUEST_DATA
            )
        if type(self.bars_available) is not int or self.bars_available < 0:
            raise PineRuntimeError(
                "coverage bars_available is invalid", code=PL_REQUEST_DATA
            )
        if self.bars_available == 0:
            if self.start_time_ms is not None or self.end_time_ms is not None:
                raise PineRuntimeError(
                    "empty coverage must not invent boundaries", code=PL_REQUEST_DATA
                )
        elif (
            type(self.start_time_ms) is not int
            or type(self.end_time_ms) is not int
            or self.end_time_ms <= self.start_time_ms
        ):
            raise PineRuntimeError(
                "coverage boundaries are invalid", code=PL_REQUEST_DATA
            )

    def identity(self) -> dict[str, object]:
        return {
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "complete": self.complete,
            "bars_available": self.bars_available,
        }

    @classmethod
    def from_dict(cls, data: object) -> DataCoverage:
        if not isinstance(data, dict) or set(data) != {
            "start_time_ms",
            "end_time_ms",
            "complete",
            "bars_available",
        }:
            raise PineRuntimeError("coverage schema mismatch", code=PL_REQUEST_DATA)
        restored = cls(
            None if data["start_time_ms"] is None else int(data["start_time_ms"]),
            None if data["end_time_ms"] is None else int(data["end_time_ms"]),
            data["complete"],
            int(data["bars_available"]),
        )
        _require_canonical_payload(
            data,
            restored.identity(),
            message="coverage is not canonical",
            code=PL_REQUEST_DATA,
        )
        return restored


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    schema_id: str
    schema_version: str
    provider_id: str
    snapshot_id: str
    query_hash: str
    revision: int
    finality: DataFinality
    mode: SnapshotMode
    parent_snapshot_hash: str | None
    coverage: DataCoverage
    bars: tuple[CanonicalBar, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_id != "openpine.marketdata.v2" or self.schema_version != "2.0.0":
            raise PineRuntimeError(
                "marketdata schema identity mismatch", code=PL_REQUEST_DATA
            )
        for name in ("provider_id", "snapshot_id"):
            _require_text(name, getattr(self, name))
        _hash(self.query_hash, "query_hash")
        if type(self.revision) is not int or self.revision < 0:
            raise PineRuntimeError("snapshot revision is invalid", code=PL_REQUEST_DATA)
        try:
            object.__setattr__(self, "finality", DataFinality(self.finality))
            object.__setattr__(self, "mode", SnapshotMode(self.mode))
        except ValueError as error:
            raise PineRuntimeError(
                "snapshot enum is invalid", code=PL_REQUEST_DATA
            ) from error
        if self.parent_snapshot_hash is not None:
            _hash(self.parent_snapshot_hash, "parent_snapshot_hash")
        if self.mode == SnapshotMode.FULL and self.parent_snapshot_hash is not None:
            raise PineRuntimeError(
                "full snapshot cannot have a parent", code=PL_REQUEST_DATA
            )
        if self.mode == SnapshotMode.APPEND and self.parent_snapshot_hash is None:
            raise PineRuntimeError(
                "append snapshot requires a parent", code=PL_REQUEST_DATA
            )
        if self.coverage.bars_available != len(self.bars):
            raise PineRuntimeError(
                "snapshot coverage count mismatch", code=PL_REQUEST_DATA
            )
        previous: CanonicalBar | None = None
        for bar in self.bars:
            if previous is not None and bar.open_time_ms < previous.close_time_ms:
                raise PineRuntimeError(
                    "snapshot bars overlap or are unsorted", code=PL_REQUEST_DATA
                )
            previous = bar
        if self.bars:
            if (
                self.coverage.start_time_ms != self.bars[0].open_time_ms
                or self.coverage.end_time_ms != self.bars[-1].close_time_ms
            ):
                raise PineRuntimeError(
                    "snapshot coverage boundaries mismatch", code=PL_REQUEST_DATA
                )
            if self.finality == DataFinality.FINAL and any(
                bar.finality != DataFinality.FINAL for bar in self.bars
            ):
                raise PineRuntimeError(
                    "final snapshot contains developing bars", code=PL_REQUEST_DATA
                )
        _hash(self.content_hash, "snapshot content_hash")
        if self.content_hash != sha(self.body()):
            raise PineRuntimeError(
                "snapshot content hash mismatch", code=PL_REQUEST_DATA
            )

    def body(self) -> dict[str, object]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "snapshot_id": self.snapshot_id,
            "query_hash": self.query_hash,
            "revision": self.revision,
            "finality": self.finality.value,
            "mode": self.mode.value,
            "parent_snapshot_hash": self.parent_snapshot_hash,
            "coverage": self.coverage.identity(),
            "bars": [bar.identity() for bar in self.bars],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.body(), "content_hash": self.content_hash}

    @classmethod
    def seal(
        cls,
        *,
        provider_id: str,
        snapshot_id: str,
        query: RequestQuery,
        revision: int,
        finality: DataFinality,
        coverage: DataCoverage,
        bars: Sequence[CanonicalBar],
        mode: SnapshotMode = SnapshotMode.FULL,
        parent_snapshot_hash: str | None = None,
    ) -> DataSnapshot:
        body = {
            "schema_id": "openpine.marketdata.v2",
            "schema_version": "2.0.0",
            "provider_id": provider_id,
            "snapshot_id": snapshot_id,
            "query_hash": query.content_hash,
            "revision": revision,
            "finality": DataFinality(finality).value,
            "mode": SnapshotMode(mode).value,
            "parent_snapshot_hash": parent_snapshot_hash,
            "coverage": coverage.identity(),
            "bars": [bar.identity() for bar in bars],
        }
        return cls(
            "openpine.marketdata.v2",
            "2.0.0",
            provider_id,
            snapshot_id,
            query.content_hash,
            revision,
            DataFinality(finality),
            SnapshotMode(mode),
            parent_snapshot_hash,
            coverage,
            tuple(bars),
            sha(body),
        )

    @classmethod
    def from_dict(cls, data: object) -> DataSnapshot:
        if not isinstance(data, dict):
            raise PineRuntimeError("snapshot must be an object", code=PL_REQUEST_DATA)
        required = {
            "schema_id",
            "schema_version",
            "provider_id",
            "snapshot_id",
            "query_hash",
            "revision",
            "finality",
            "mode",
            "parent_snapshot_hash",
            "coverage",
            "bars",
            "content_hash",
        }
        if set(data) != required or not isinstance(data["bars"], list):
            raise PineRuntimeError("snapshot schema mismatch", code=PL_REQUEST_DATA)
        restored = cls(
            str(data["schema_id"]),
            str(data["schema_version"]),
            str(data["provider_id"]),
            str(data["snapshot_id"]),
            str(data["query_hash"]),
            int(data["revision"]),
            DataFinality(str(data["finality"])),
            SnapshotMode(str(data["mode"])),
            (
                None
                if data["parent_snapshot_hash"] is None
                else str(data["parent_snapshot_hash"])
            ),
            DataCoverage.from_dict(data["coverage"]),
            tuple(CanonicalBar.from_dict(row) for row in data["bars"]),
            str(data["content_hash"]),
        )
        _require_canonical_payload(
            data,
            restored.to_dict(),
            message="snapshot is not canonical",
            code=PL_REQUEST_DATA,
        )
        return restored


@dataclass(frozen=True, slots=True)
class RequestDatasetKey:
    query: RequestQuery
    snapshot_hash: str
    result_shape_hash: str
    invalid_symbol: bool
    key_hash: str

    def __post_init__(self) -> None:
        if type(self.invalid_symbol) is not bool:
            raise PineRuntimeError(
                "request dataset invalid_symbol must be a bool",
                code=PL_REQUEST_IDENTITY,
            )
        _hash(self.snapshot_hash, "snapshot_hash")
        _hash(self.result_shape_hash, "result_shape_hash")
        _hash(self.key_hash, "request dataset key_hash")
        if self.key_hash != sha(self.body()):
            raise PineRuntimeError(
                "request dataset key hash mismatch", code=PL_REQUEST_IDENTITY
            )

    def body(self) -> dict[str, object]:
        return {
            "query": self.query.identity(),
            "snapshot_hash": self.snapshot_hash,
            "result_shape_hash": self.result_shape_hash,
            "invalid_symbol": self.invalid_symbol,
        }

    @classmethod
    def create(
        cls, query: RequestQuery, snapshot_hash: str, shape: ResultShape
    ) -> RequestDatasetKey:
        body = {
            "query": query.identity(),
            "snapshot_hash": snapshot_hash,
            "result_shape_hash": shape.content_hash,
            "invalid_symbol": False,
        }
        return cls(query, snapshot_hash, shape.content_hash, False, sha(body))

    @classmethod
    def invalid(cls, query: RequestQuery, shape: ResultShape) -> RequestDatasetKey:
        snapshot_hash = sha({"invalid_symbol_query": query.content_hash})
        body = {
            "query": query.identity(),
            "snapshot_hash": snapshot_hash,
            "result_shape_hash": shape.content_hash,
            "invalid_symbol": True,
        }
        return cls(query, snapshot_hash, shape.content_hash, True, sha(body))

    def to_dict(self) -> dict[str, object]:
        return {**self.body(), "key_hash": self.key_hash}

    @classmethod
    def from_dict(cls, data: object) -> RequestDatasetKey:
        if not isinstance(data, dict) or set(data) != {
            "query",
            "snapshot_hash",
            "result_shape_hash",
            "invalid_symbol",
            "key_hash",
        }:
            raise PineRuntimeError(
                "request dataset key schema mismatch", code=PL_REQUEST_IDENTITY
            )
        return cls(
            RequestQuery.from_dict(data["query"]),
            str(data["snapshot_hash"]),
            str(data["result_shape_hash"]),
            data["invalid_symbol"],
            str(data["key_hash"]),
        )


@dataclass(frozen=True, slots=True)
class RequestChildContext:
    language_hash: str
    policy_hash: str
    instrument_id: str
    timeframe: str
    dataset_key_hash: str
    namespace: str
    parent_runtime_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "language_hash",
            "policy_hash",
            "dataset_key_hash",
            "parent_runtime_hash",
            "content_hash",
        ):
            _hash(getattr(self, name), name)
        _require_text("instrument_id", self.instrument_id)
        _require_text("timeframe", self.timeframe)
        _require_text("namespace", self.namespace)
        if self.content_hash != sha(self.body()):
            raise PineRuntimeError(
                "child context hash mismatch", code=PL_REQUEST_IDENTITY
            )

    def body(self) -> dict[str, object]:
        return {
            "language_hash": self.language_hash,
            "policy_hash": self.policy_hash,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "dataset_key_hash": self.dataset_key_hash,
            "namespace": self.namespace,
            "parent_runtime_hash": self.parent_runtime_hash,
        }

    @classmethod
    def seal(
        cls,
        *,
        language_hash: str,
        policy_hash: str,
        instrument_id: str,
        timeframe: str,
        dataset_key_hash: str,
        namespace: str,
        parent_runtime_hash: str,
    ) -> RequestChildContext:
        body = {
            "language_hash": language_hash,
            "policy_hash": policy_hash,
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "dataset_key_hash": dataset_key_hash,
            "namespace": namespace,
            "parent_runtime_hash": parent_runtime_hash,
        }
        return cls(**body, content_hash=sha(body))

    def to_dict(self) -> dict[str, object]:
        return {**self.body(), "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, data: object) -> RequestChildContext:
        if not isinstance(data, dict) or set(data) != {
            "language_hash",
            "policy_hash",
            "instrument_id",
            "timeframe",
            "dataset_key_hash",
            "namespace",
            "parent_runtime_hash",
            "content_hash",
        }:
            raise PineRuntimeError(
                "child context schema mismatch", code=PL_REQUEST_IDENTITY
            )
        restored = cls(**{key: str(value) for key, value in data.items()})
        _require_canonical_payload(
            data,
            restored.to_dict(),
            message="child context is not canonical",
            code=PL_REQUEST_IDENTITY,
        )
        return restored


@dataclass(frozen=True, slots=True)
class EvaluatedBar:
    open_time_ms: int
    close_time_ms: int
    finality: DataFinality
    revision: int
    value: object

    def __post_init__(self) -> None:
        if (
            type(self.open_time_ms) is not int
            or type(self.close_time_ms) is not int
            or self.close_time_ms <= self.open_time_ms
        ):
            raise PineRuntimeError(
                "evaluated bar boundaries are invalid", code=PL_REQUEST_DATA
            )
        if type(self.revision) is not int or self.revision < 0:
            raise PineRuntimeError(
                "evaluated bar revision is invalid", code=PL_REQUEST_DATA
            )
        try:
            object.__setattr__(self, "finality", DataFinality(self.finality))
        except ValueError as error:
            raise PineRuntimeError(
                "evaluated bar finality is invalid", code=PL_REQUEST_DATA
            ) from error
        object.__setattr__(self, "value", to_portable(self.value))

    def to_dict(self) -> dict[str, object]:
        return {
            "open_time_ms": self.open_time_ms,
            "close_time_ms": self.close_time_ms,
            "finality": self.finality.value,
            "revision": self.revision,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: object) -> EvaluatedBar:
        if not isinstance(data, dict) or set(data) != {
            "open_time_ms",
            "close_time_ms",
            "finality",
            "revision",
            "value",
        }:
            raise PineRuntimeError(
                "evaluated bar schema mismatch", code=PL_REQUEST_DATA
            )
        restored = cls(
            int(data["open_time_ms"]),
            int(data["close_time_ms"]),
            DataFinality(str(data["finality"])),
            int(data["revision"]),
            data["value"],
        )
        _require_canonical_payload(
            data,
            restored.to_dict(),
            message="evaluated bar is not canonical",
            code=PL_REQUEST_DATA,
        )
        return restored


@dataclass(frozen=True, slots=True)
class RequestDataset:
    status: DatasetStatus
    key: RequestDatasetKey
    result_shape: ResultShape
    snapshot: DataSnapshot | None
    evaluated_bars: tuple[EvaluatedBar, ...]
    child_context: RequestChildContext | None
    child_state: dict[str, object]
    lineage_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "status", DatasetStatus(self.status))
        except ValueError as error:
            raise PineRuntimeError(
                "dataset status is invalid", code=PL_REQUEST_DATA
            ) from error
        _hash(self.lineage_hash, "lineage_hash")
        _hash(self.content_hash, "dataset content_hash")
        object.__setattr__(self, "child_state", to_portable(self.child_state))
        if self.status == DatasetStatus.READY:
            if self.snapshot is None or self.child_context is None:
                raise PineRuntimeError(
                    "ready dataset is incomplete", code=PL_REQUEST_DATA
                )
            if (
                self.key.snapshot_hash != self.snapshot.content_hash
                or self.snapshot.query_hash != self.key.query.content_hash
                or self.lineage_hash != self.key.query.lineage_hash
            ):
                raise PineRuntimeError(
                    "dataset snapshot identity mismatch", code=PL_REQUEST_IDENTITY
                )
            if (
                self.child_context.dataset_key_hash != self.key.key_hash
                or self.child_context.instrument_id != self.key.query.instrument_id
                or self.child_context.timeframe != self.key.query.timeframe
            ):
                raise PineRuntimeError(
                    "dataset child context mismatch", code=PL_REQUEST_IDENTITY
                )
            if self.snapshot.mode == SnapshotMode.FULL:
                if len(self.snapshot.bars) != len(self.evaluated_bars):
                    raise PineRuntimeError(
                        "dataset evaluation count mismatch", code=PL_REQUEST_DATA
                    )
                compared = self.evaluated_bars
            else:
                if len(self.evaluated_bars) < len(self.snapshot.bars):
                    raise PineRuntimeError(
                        "append dataset lost parent history", code=PL_REQUEST_DATA
                    )
                compared = (
                    self.evaluated_bars[-len(self.snapshot.bars) :]
                    if self.snapshot.bars
                    else ()
                )
            for source, evaluated in zip(self.snapshot.bars, compared, strict=True):
                if (
                    source.open_time_ms,
                    source.close_time_ms,
                    source.finality,
                    source.revision,
                ) != (
                    evaluated.open_time_ms,
                    evaluated.close_time_ms,
                    evaluated.finality,
                    evaluated.revision,
                ):
                    raise PineRuntimeError(
                        "dataset bar lineage mismatch", code=PL_REQUEST_DATA
                    )
            for evaluated in self.evaluated_bars:
                normalized = self.result_shape.validate(
                    self.result_shape.restore(evaluated.value)
                )
                if canonical_json(normalized) != canonical_json(evaluated.value):
                    raise PineRuntimeError(
                        "stored request result is not canonical",
                        code=PL_REQUEST_RESULT_SHAPE,
                    )
        elif (
            self.snapshot is not None
            or self.evaluated_bars
            or self.child_context is not None
            or self.child_state
        ):
            raise PineRuntimeError(
                "invalid-symbol dataset must be empty", code=PL_REQUEST_DATA
            )
        if self.key.result_shape_hash != self.result_shape.content_hash:
            raise PineRuntimeError(
                "dataset result shape hash mismatch", code=PL_REQUEST_IDENTITY
            )
        if self.content_hash != sha(self.body()):
            raise PineRuntimeError(
                "dataset content hash mismatch", code=PL_REQUEST_DATA
            )

    def body(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "key": self.key.to_dict(),
            "result_shape": self.result_shape.identity(),
            "snapshot": None if self.snapshot is None else self.snapshot.to_dict(),
            "evaluated_bars": [bar.to_dict() for bar in self.evaluated_bars],
            "child_context": (
                None if self.child_context is None else self.child_context.to_dict()
            ),
            "child_state": self.child_state,
            "lineage_hash": self.lineage_hash,
        }

    @classmethod
    def ready(
        cls,
        *,
        key: RequestDatasetKey,
        shape: ResultShape,
        snapshot: DataSnapshot,
        evaluated_bars: Sequence[EvaluatedBar],
        child_context: RequestChildContext,
        child_state: Mapping[str, object],
        lineage_hash: str,
    ) -> RequestDataset:
        portable_state = to_portable(dict(child_state))
        if not isinstance(portable_state, dict):
            raise PineRuntimeError(
                "request child state is invalid", code=PL_REQUEST_RESULT_SHAPE
            )
        body: dict[str, object] = {
            "status": DatasetStatus.READY.value,
            "key": key.to_dict(),
            "result_shape": shape.identity(),
            "snapshot": snapshot.to_dict(),
            "evaluated_bars": [bar.to_dict() for bar in evaluated_bars],
            "child_context": child_context.to_dict(),
            "child_state": portable_state,
            "lineage_hash": lineage_hash,
        }
        return cls(
            DatasetStatus.READY,
            key,
            shape,
            snapshot,
            tuple(evaluated_bars),
            child_context,
            portable_state,
            lineage_hash,
            sha(body),
        )

    @classmethod
    def invalid_symbol(cls, query: RequestQuery, shape: ResultShape) -> RequestDataset:
        key = RequestDatasetKey.invalid(query, shape)
        body: dict[str, object] = {
            "status": DatasetStatus.INVALID_SYMBOL.value,
            "key": key.to_dict(),
            "result_shape": shape.identity(),
            "snapshot": None,
            "evaluated_bars": [],
            "child_context": None,
            "child_state": {},
            "lineage_hash": query.lineage_hash,
        }
        return cls(
            DatasetStatus.INVALID_SYMBOL,
            key,
            shape,
            None,
            (),
            None,
            {},
            query.lineage_hash,
            sha(body),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.body(), "content_hash": self.content_hash}

    def value(self, index: int) -> object:
        try:
            row = self.evaluated_bars[index]
        except IndexError as error:
            raise PineRuntimeError(
                "dataset value index out of bounds", code=PL_REQUEST_DATA
            ) from error
        return self.result_shape.restore(row.value)

    @classmethod
    def from_dict(cls, data: object) -> RequestDataset:
        if not isinstance(data, dict):
            raise PineRuntimeError(
                "request dataset must be an object", code=PL_REQUEST_DATA
            )
        required = {
            "status",
            "key",
            "result_shape",
            "snapshot",
            "evaluated_bars",
            "child_context",
            "child_state",
            "lineage_hash",
            "content_hash",
        }
        if (
            set(data) != required
            or not isinstance(data["evaluated_bars"], list)
            or not isinstance(data["child_state"], dict)
        ):
            raise PineRuntimeError(
                "request dataset schema mismatch", code=PL_REQUEST_DATA
            )
        return cls(
            DatasetStatus(str(data["status"])),
            RequestDatasetKey.from_dict(data["key"]),
            ResultShape.from_dict(data["result_shape"]),
            (
                None
                if data["snapshot"] is None
                else DataSnapshot.from_dict(data["snapshot"])
            ),
            tuple(EvaluatedBar.from_dict(row) for row in data["evaluated_bars"]),
            (
                None
                if data["child_context"] is None
                else RequestChildContext.from_dict(data["child_context"])
            ),
            dict(data["child_state"]),
            str(data["lineage_hash"]),
            str(data["content_hash"]),
        )
