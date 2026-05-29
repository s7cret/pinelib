from pinelib.plot import PlotRecorder


def test_plot_recorder_time_window_filters_records():
    recorder = PlotRecorder()
    recorder.set_time_window(100, 200)

    recorder.record_plot(50, 0, 1.0, "A")
    recorder.record_plot(100, 1, 2.0, "A")
    recorder.record(200, 2, "plot", 3.0, "B")
    recorder.record(250, 3, "plot", 4.0, "B")

    records = recorder.get_records()
    assert len(records) == 2
    assert records[0] == (100, 1, 2.0, "A")
    assert records[1].bar_time == 200
    assert records[1].value == 3.0


def test_plot_recorder_snapshots_mutable_scalar_values():
    class Scalar:
        def __init__(self, value):
            self._current = value

    value = Scalar(1)
    recorder = PlotRecorder()

    recorder.record_plot(100, 1, value, "A")
    value._current = 2
    recorder.record(200, 2, "plot", value, "B")
    value._current = 3

    records = recorder.get_records()
    assert records[0] == (100, 1, 1, "A")
    assert records[1].value == 2
