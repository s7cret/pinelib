from pinelib.core import Bar
from pinelib.strategy import StrategyContext


def test_ohlc_path_tie_uses_low_first_tradingview_rule():
    assert StrategyContext.ohlc_path(Bar(time=1, open=10, high=12, low=8, close=10)) == [
        10,
        8,
        12,
        10,
    ]
