from __future__ import annotations
from pinelib.builtins.color import color_constant, color_component
from pinelib.runtime.session import RuntimeTransaction

def r_v1(color: object) -> object:
    return color_component(color, "r")

def g_v1(color: object) -> object:
    return color_component(color, "g")

def b_v1(color: object) -> object:
    return color_component(color, "b")

def t_v1(color: object) -> object:
    return color_component(color, "t")

def aqua_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("aqua", tx.session.language.pine_version)

def black_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("black", tx.session.language.pine_version)

def blue_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("blue", tx.session.language.pine_version)

def fuchsia_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("fuchsia", tx.session.language.pine_version)

def gray_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("gray", tx.session.language.pine_version)

def green_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("green", tx.session.language.pine_version)

def lime_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("lime", tx.session.language.pine_version)

def maroon_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("maroon", tx.session.language.pine_version)

def navy_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("navy", tx.session.language.pine_version)

def olive_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("olive", tx.session.language.pine_version)

def orange_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("orange", tx.session.language.pine_version)

def purple_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("purple", tx.session.language.pine_version)

def red_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("red", tx.session.language.pine_version)

def silver_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("silver", tx.session.language.pine_version)

def teal_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("teal", tx.session.language.pine_version)

def white_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("white", tx.session.language.pine_version)

def yellow_v1(tx: RuntimeTransaction) -> str:
    tx._check()
    return color_constant("yellow", tx.session.language.pine_version)

