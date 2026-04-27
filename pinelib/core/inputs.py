from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pinelib.core.timefunc import parse_session
from pinelib.core.types import RuntimeConfig, parse_timeframe_to_ms
from pinelib.errors import PL_INPUT_VALIDATION_ERROR, PineRuntimeError

InputKind = Literal["int", "float", "bool", "string", "timeframe", "symbol", "session", "source"]


@dataclass(frozen=True, slots=True)
class InputMetadata:
    name: str
    kind: InputKind
    title: str | None
    default: object
    value: object
    minval: builtins.int | builtins.float | None = None
    maxval: builtins.int | builtins.float | None = None
    options: tuple[object, ...] | None = None


class InputRegistry:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.metadata: dict[str, InputMetadata] = {}

    def int(
        self,
        name: str,
        default: builtins.int,
        *,
        title: str | None = None,
        minval: builtins.int | None = None,
        maxval: builtins.int | None = None,
        options: Sequence[builtins.int] | None = None,
    ) -> builtins.int:
        if type(default) is not builtins.int:
            self._fail(name, "input.int default must be int")
        self._register(name, "int", default, title, minval, maxval, options)
        return default

    def float(
        self,
        name: str,
        default: builtins.float | builtins.int,
        *,
        title: str | None = None,
        minval: builtins.float | builtins.int | None = None,
        maxval: builtins.float | builtins.int | None = None,
        options: Sequence[builtins.float | builtins.int] | None = None,
    ) -> builtins.float:
        if not isinstance(default, builtins.int | builtins.float) or isinstance(default, bool):
            self._fail(name, "input.float default must be numeric")
        value = builtins.float(default)
        self._register(name, "float", value, title, minval, maxval, options)
        return value

    def bool(self, name: str, default: bool, *, title: str | None = None) -> bool:
        if type(default) is not bool:
            self._fail(name, "input.bool default must be bool")
        self._register(name, "bool", default, title)
        return default

    def string(
        self,
        name: str,
        default: str,
        *,
        title: str | None = None,
        options: Sequence[str] | None = None,
    ) -> str:
        if type(default) is not str:
            self._fail(name, "input.string default must be str")
        self._register(name, "string", default, title, options=options)
        return default

    def timeframe(
        self,
        name: str,
        default: str,
        *,
        title: str | None = None,
        options: Sequence[str] | None = None,
    ) -> str:
        if parse_timeframe_to_ms(default) is None:
            self._fail(name, f"Invalid timeframe: {default}")
        if options is not None:
            for option in options:
                if parse_timeframe_to_ms(option) is None:
                    self._fail(name, f"Invalid timeframe option: {option}")
        self._register(name, "timeframe", default, title, options=options)
        return default

    def symbol(self, name: str, default: str, *, title: str | None = None) -> str:
        if type(default) is not str or not default.strip():
            self._fail(name, "input.symbol default must be a non-empty string")
        self._register(name, "symbol", default, title)
        return default

    def session(self, name: str, default: str, *, title: str | None = None, timezone: str = "UTC") -> str:
        parse_session(default, timezone)
        self._register(name, "session", default, title)
        return default

    def source(self, name: str, default: object, *, title: str | None = None) -> object:
        if default is None:
            self._fail(name, "input.source default is required")
        return self._register(name, "source", default, title).value

    def _register(
        self,
        name: str,
        kind: InputKind,
        default: object,
        title: str | None,
        minval: builtins.int | builtins.float | None = None,
        maxval: builtins.int | builtins.float | None = None,
        options: Sequence[object] | None = None,
    ) -> InputMetadata:
        if minval is not None and maxval is not None and minval > maxval:
            self._fail(name, "input minval cannot be greater than maxval")
        normalized_options = tuple(options) if options is not None else None
        if normalized_options is not None and default not in normalized_options:
            self._fail(name, "input default must be one of options")
        if minval is not None and isinstance(default, builtins.int | builtins.float) and default < minval:
            self._fail(name, "input default is below minval")
        if maxval is not None and isinstance(default, builtins.int | builtins.float) and default > maxval:
            self._fail(name, "input default is above maxval")
        meta = InputMetadata(
            name=name,
            kind=kind,
            title=title,
            default=default,
            value=default,
            minval=minval,
            maxval=maxval,
            options=normalized_options,
        )
        self.metadata[name] = meta
        return meta

    def _fail(self, name: str, message: str) -> None:
        diagnostic: dict[str, object] = {
            "code": PL_INPUT_VALIDATION_ERROR,
            "input": name,
            "message": message,
        }
        self.config.diagnostics.append(diagnostic)
        raise PineRuntimeError(message, code=PL_INPUT_VALIDATION_ERROR)
