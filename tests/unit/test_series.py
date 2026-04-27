from pinelib import Series, na


def test_series_current_and_committed_history_are_separate() -> None:
    series: Series[float] = Series(name="x", dtype="float")
    series.set_current(10.0)
    assert series[0] == 10.0
    assert series[1] is na

    series.commit_current()
    series.set_current(20.0)
    assert series[0] == 20.0
    assert series[1] == 10.0


def test_missing_bool_history_returns_false() -> None:
    series: Series[bool] = Series(name="flag", dtype="bool", initial=False)
    assert series[1] is False
