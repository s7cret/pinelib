import pytest

from pinelib import Bar, InMemoryDataProvider, PineDataFormatError


def test_in_memory_provider_validates_order_and_duplicates() -> None:
    first = Bar(time=10, open=1.0, high=2.0, low=0.5, close=1.5)
    second = Bar(time=20, open=1.5, high=2.5, low=1.0, close=2.0)

    provider = InMemoryDataProvider({("TEST:AAA", "60"): [first, second]})
    assert provider.get_bars("TEST:AAA", "60", None, None) == [first, second]

    with pytest.raises(PineDataFormatError):
        InMemoryDataProvider({("TEST:AAA", "60"): [second, first]})

    with pytest.raises(PineDataFormatError):
        InMemoryDataProvider({("TEST:AAA", "60"): [first, first]})


def test_provider_filters_by_start_end_and_max_bars() -> None:
    bars = [
        Bar(time=10, open=1.0, high=2.0, low=0.5, close=1.5),
        Bar(time=20, open=1.5, high=2.5, low=1.0, close=2.0),
        Bar(time=30, open=2.0, high=3.0, low=1.5, close=2.5),
    ]
    provider = InMemoryDataProvider({("TEST:AAA", "60"): bars})
    assert provider.get_bars("TEST:AAA", "60", 15, 30, max_bars=1) == [bars[1]]
    assert provider.get_bars("TEST:AAA", "60", 10, 30) == [bars[0], bars[1]]
