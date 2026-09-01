from __future__ import annotations

from typing import cast

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
