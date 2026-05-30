from pinelib import ta
from pinelib.core.na import na
from pinelib.ta import utils, volume


def test_volume_cum_reexport_and_batch_behavior() -> None:
    assert ta.cum is volume.cum
    assert "cum" in ta.__all__
    assert "cum" in volume.__all__
    assert ta.cum([1.0, na, 2.5, -0.5]) == [1.0, 1.0, 3.5, 3.0]


def test_utils_reexports_series_history_helpers() -> None:
    assert ta._history is utils._history
    assert ta.shifted_series is utils.shifted_series
    assert ta.hl2_series is utils.hl2_series
    assert ta.hlc3_series is utils.hlc3_series
    assert ta.ohlc4_series is utils.ohlc4_series
    assert ta.hlcc4_series is utils.hlcc4_series
    assert "_history" in ta.__all__
    assert "shifted_series" in ta.__all__
    assert "_history" in utils.__all__
    assert "shifted_series" in utils.__all__
