from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pinelib.runtime.session import RuntimeTransaction

from pinelib.input import InputRegistry


def bool_v1(registry: InputRegistry, input_id: str) -> bool:
    return cast(bool, registry.get(input_id, "bool"))


def int_v1(registry: InputRegistry, input_id: str) -> int:
    return cast(int, registry.get(input_id, "int"))


def float_v1(registry: InputRegistry, input_id: str) -> float:
    return float(cast(int | float, registry.get(input_id, "float")))


def string_v1(registry: InputRegistry, input_id: str) -> str:
    return cast(str, registry.get(input_id, "string"))


def time_v1(registry: InputRegistry, input_id: str) -> int:
    return cast(int, registry.get(input_id, "time"))


def price_v1(registry: InputRegistry, input_id: str) -> float:
    return float(cast(int | float, registry.get(input_id, "price")))


def symbol_v1(registry: InputRegistry, input_id: str) -> str:
    return cast(str, registry.get(input_id, "symbol"))


def timeframe_v1(registry: InputRegistry, input_id: str) -> str:
    return cast(str, registry.get(input_id, "timeframe"))


def session_v1(registry: InputRegistry, input_id: str) -> str:
    return cast(str, registry.get(input_id, "session"))


def color_v1(registry: InputRegistry, input_id: str) -> str:
    return cast(str, registry.get(input_id, "color"))


def source_v1(registry: InputRegistry, input_id: str) -> str:
    return cast(str, registry.get(input_id, "source"))


def source_value_v1(
    tx: RuntimeTransaction, registry: InputRegistry, input_id: str
) -> object:
    """Resolve an admitted built-in source against this callback, never a string value."""
    from pinelib.core.values import pine_binary

    name = cast(str, registry.get(input_id, "source"))
    if name in {"open", "high", "low", "close", "volume"}:
        return getattr(tx, "value_" + name)
    components = {
        "hl2": ("high", "low"),
        "hlc3": ("high", "low", "close"),
        "ohlc4": ("open", "high", "low", "close"),
        "hlcc4": ("high", "low", "close", "close"),
    }
    if name not in components:
        from pinelib.errors import PL_INPUT_INVALID, PineRuntimeError

        raise PineRuntimeError(
            "external input source requires an admitted source provider",
            code=PL_INPUT_INVALID,
        )
    values = [getattr(tx, "value_" + field) for field in components[name]]
    result = values[0]
    for value in values[1:]:
        result = pine_binary("+", result, value, tx.session.language)
    return pine_binary("/", result, float(len(values)), tx.session.language)


def generic_v1(
    tx: RuntimeTransaction, registry: InputRegistry, input_id: str
) -> object:
    if registry.spec(input_id).kind == "source":
        return source_value_v1(tx, registry, input_id)
    return registry.get(input_id)
