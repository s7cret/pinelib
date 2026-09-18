"""Pine hexadecimal RGBA values. Palette changes are explicitly versioned.

Authority: TradingView visuals/colors and migration-guides/to-pine-version-6.
"""
from __future__ import annotations
import re
from pinelib.core.values import is_na, na
from pinelib.errors import PineRuntimeError, PL_VALUE_TYPE

_PALETTE_V6 = {'aqua': '#00BCD4', 'black': '#363A45', 'blue': '#2196F3', 'fuchsia': '#E040FB', 'gray': '#787B86', 'green': '#4CAF50', 'lime': '#00E676', 'maroon': '#880E4F', 'navy': '#311B92', 'olive': '#808000', 'orange': '#FF9800', 'purple': '#9C27B0', 'red': '#F23645', 'silver': '#B2B5BE', 'teal': '#089981', 'white': '#FFFFFF', 'yellow': '#FDD835'}
_PALETTE_OLD = dict(_PALETTE_V6, red="#FF5252", teal="#00897B", yellow="#FFEB3B")

def color_constant(name: str, pine_version: int) -> str:
    if pine_version not in (4, 5, 6) or name not in _PALETTE_V6:
        raise PineRuntimeError("color constant is not admitted for this version", code=PL_VALUE_TYPE)
    return (_PALETTE_V6 if pine_version >= 6 else _PALETTE_OLD)[name]

def color_component(value: object, channel: str) -> object:
    if is_na(value):
        return na
    if channel not in {"r", "g", "b", "t"} or not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value) is None:
        raise PineRuntimeError("expected a Pine hexadecimal color", code=PL_VALUE_TYPE)
    if channel == "t":
        alpha = int(value[7:9], 16) if len(value) == 9 else 255
        return 100.0 * (255 - alpha) / 255
    start = {"r": 1, "g": 3, "b": 5}[channel]
    return float(int(value[start:start + 2], 16))
