from pinelib import ta
from pinelib.core.na import na
from pinelib.ta import volume


def test_volume_cum_reexport_and_batch_behavior() -> None:
    assert ta.cum is volume.cum
    assert "cum" in ta.__all__
    assert "cum" in volume.__all__
    assert ta.cum([1.0, na, 2.5, -0.5]) == [1.0, 1.0, 3.5, 3.0]
