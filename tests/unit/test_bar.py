import pytest

from pinelib import Bar, PineDataFormatError
from pinelib.core.bar import from_contract_bar, to_contract_bar
from marketdata_provider.contracts import InstrumentKey, parse_timeframe
from marketdata_provider.contracts.bar import Bar as ContractBar


def test_bar_validates_ohlc_relationships() -> None:
    with pytest.raises(PineDataFormatError):
        Bar(time=1, open=10.0, high=9.0, low=8.0, close=9.5)

    with pytest.raises(PineDataFormatError):
        Bar(time=1, open=10.0, high=12.0, low=10.5, close=11.0)


def test_bar_rejects_time_close_before_time() -> None:
    with pytest.raises(PineDataFormatError):
        Bar(time=10, time_close=9, open=1.0, high=1.5, low=0.5, close=1.2)


def test_to_contract_bar_fills_fixed_close_time_and_preserves_identity() -> None:
    instrument = InstrumentKey("binance", "spot", "BTCUSDT")
    timeframe = parse_timeframe("1m")

    contract = to_contract_bar(
        Bar(time=60_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0),
        instrument=instrument,
        timeframe=timeframe,
        closed=False,
    )

    assert contract.instrument == instrument
    assert contract.timeframe == timeframe
    assert contract.time_close == 119_999
    assert contract.closed is False


def test_to_contract_bar_rejects_missing_close_time_for_monthly_timeframe() -> None:
    with pytest.raises(PineDataFormatError, match="time_close is required"):
        to_contract_bar(
            Bar(time=0, open=1.0, high=1.0, low=1.0, close=1.0),
            instrument=InstrumentKey("binance", "spot", "BTCUSDT"),
            timeframe=parse_timeframe("1M"),
        )


def test_to_contract_bar_translates_contract_validation_errors() -> None:
    with pytest.raises(PineDataFormatError, match="time_close must be greater"):
        to_contract_bar(
            Bar(time=10, time_close=10, open=1.0, high=1.0, low=1.0, close=1.0),
            instrument=InstrumentKey("binance", "spot", "BTCUSDT"),
            timeframe=parse_timeframe("1m"),
        )


def test_from_contract_bar_converts_missing_volume_to_pine_default() -> None:
    instrument = InstrumentKey("binance", "spot", "BTCUSDT")
    timeframe = parse_timeframe("1m")

    bar = from_contract_bar(
        ContractBar(instrument, timeframe, 0, 59_999, 1.0, 1.0, 1.0, 1.0, None, True)
    )

    assert bar == Bar(time=0, time_close=59_999, open=1.0, high=1.0, low=1.0, close=1.0)
