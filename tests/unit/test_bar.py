import pytest

from pinelib import Bar, PineDataFormatError


def test_bar_validates_ohlc_relationships() -> None:
    with pytest.raises(PineDataFormatError):
        Bar(time=1, open=10.0, high=9.0, low=8.0, close=9.5)

    with pytest.raises(PineDataFormatError):
        Bar(time=1, open=10.0, high=12.0, low=10.5, close=11.0)


def test_bar_rejects_time_close_before_time() -> None:
    with pytest.raises(PineDataFormatError):
        Bar(time=10, time_close=9, open=1.0, high=1.5, low=0.5, close=1.2)
