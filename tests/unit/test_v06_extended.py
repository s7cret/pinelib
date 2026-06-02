import math

from pinelib import color, string, ta
from pinelib import math as pine_math
from pinelib.core.na import is_na, na


def test_bb_macd_dmi_extended_helpers() -> None:
    close = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    basis, upper, lower = ta.bb(close, 3, 2.0)
    assert basis[-1] == 5.0
    assert upper[-1] > basis[-1] > lower[-1]
    assert ta.bbw(close, 3, 2.0)[-1] == 100.0 * (upper[-1] - lower[-1]) / basis[-1]
    macd, signal, hist = ta.macd(close, 2, 4, 3)
    assert len(macd) == len(signal) == len(hist) == len(close)
    plus, minus, adx = ta.dmi([10, 11, 13, 14, 13, 15], [9, 9, 10, 11, 10, 12], close, 3, 3)
    assert len(plus) == len(minus) == len(adx) == len(close)
    assert any(not is_na(v) for v in adx)


def test_stoch_is_fast_unsmoothed() -> None:
    high = [10.0, 11.0, 12.0, 13.0]
    low = [0.0, 1.0, 2.0, 3.0]
    close = [5.0, 6.0, 12.0, 4.0]
    out = ta.stoch(close, high, low, 3)
    assert is_na(out[1])
    assert out[2] == 100.0
    assert out[3] == 100.0 * (4.0 - 1.0) / (13.0 - 1.0)


def test_supertrend_direction_tv_sign_convention() -> None:
    high = [10, 11, 12, 13, 14, 30, 31]
    low = [9, 10, 11, 12, 13, 29, 30]
    close = [9.5, 10.5, 11.5, 12.5, 13.5, 29.5, 30.5]
    _, direction = ta.supertrend(1.0, 2, high=high, low=low, close=close)
    # TV: -1 is uptrend/green
    assert any(d == -1 for d in direction if not is_na(d))
    assert all(d in (na, 1, -1) for d in direction)


def test_valuewhen_and_barssince() -> None:
    cond = [False, True, False, True, False]
    src = [10, 20, 30, 40, 50]
    assert ta.valuewhen(cond, src, 0) == [na, 20, 20, 40, 40]
    assert ta.valuewhen(cond, src, 1) == [na, na, na, 20, 20]
    assert ta.barssince(cond) == [na, 0, 1, 0, 1]


def test_string_color_math_helpers() -> None:
    assert string.upper("ab") == "AB"
    assert string.contains("pine", "in")
    assert string.tonumber("1.5") == 1.5
    assert string.pos("BINANCE:BTCUSDT", ":") == 7
    assert string.pos("BINANCE:BTCUSDT", "BTC", 8) == 8
    assert string.pos("BINANCE:BTCUSDT", "ETH") is string.na
    c = color.rgb(10, 20, 30, 50)
    assert (color.r(c), color.g(c), color.b(c), color.t(c)) == (10, 20, 30, 50)
    assert color.lime.to_hex() == "#00ff0000"
    assert color.aqua.to_hex() == "#00ffff00"
    assert color.new(color.lime, 25).to_hex() == "#00ff0040"
    assert pine_math.sqrt(9) == 3
    assert pine_math.sign(-2) == -1
    assert pine_math.avg(1, 2, 3) == 2
    assert math.isclose(pine_math.todegrees(math.pi), 180.0)
