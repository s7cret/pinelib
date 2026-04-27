import pytest

from pinelib import PineTypeError, Series, fixnan, is_na, na, nz


def test_is_na_supports_none_nan_and_sentinel() -> None:
    assert is_na(None)
    assert is_na(float("nan"))
    assert is_na(na)


def test_nz_rejects_bool_arguments() -> None:
    with pytest.raises(PineTypeError):
        nz(True)

    with pytest.raises(PineTypeError):
        nz(na, False)


def test_fixnan_rejects_bool_and_backfills_series_history() -> None:
    with pytest.raises(PineTypeError):
        fixnan(False)

    series: Series[float] = Series(name="close_copy", dtype="float")
    series.set_current(1.0)
    series.commit_current()
    series.set_current(na)
    assert fixnan(series) == 1.0
