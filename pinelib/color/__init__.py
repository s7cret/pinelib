from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Color:
    r: int
    g: int
    b: int
    a: int = 0

    def __post_init__(self) -> None:
        for name, value in (("r", self.r), ("g", self.g), ("b", self.b), ("a", self.a)):
            if not 0 <= int(value) <= 255:
                raise ValueError(f"color component {name} must be 0..255")

    def to_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}{self.a:02x}"


def rgb(red: int, green: int, blue: int, transp: int = 0) -> Color:
    # Pine transparency is 0 opaque .. 100 transparent; store as alpha byte compatible with existing v0.6 consumers.  # noqa: E501
    alpha = round(max(0, min(100, transp)) * 255 / 100)
    return Color(int(red), int(green), int(blue), alpha)


def new(color: Color, transp: int) -> Color:
    return rgb(color.r, color.g, color.b, transp)


def r(color: Color) -> int:
    return color.r


def g(color: Color) -> int:
    return color.g


def b(color: Color) -> int:
    return color.b


def t(color: Color) -> int:
    return round(color.a * 100 / 255)


black = rgb(0, 0, 0)
white = rgb(255, 255, 255)
red = rgb(255, 0, 0)
green = rgb(0, 128, 0)
blue = rgb(0, 0, 255)
yellow = rgb(255, 255, 0)
orange = rgb(255, 165, 0)
purple = rgb(128, 0, 128)
gray = rgb(128, 128, 128)

__all__ = [
    "Color",
    "rgb",
    "new",
    "r",
    "g",
    "b",
    "t",
    "black",
    "white",
    "red",
    "green",
    "blue",
    "yellow",
    "orange",
    "purple",
    "gray",
]
