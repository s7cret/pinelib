"""ABI surface regressions with independently specified observable results."""

from statistics import mean, pstdev

import pytest

from pinelib import CallbackFrame
from pinelib.abi import reference, runtime_values, ta, visual
from pinelib.core import is_na
from pinelib.runtime import BarValues
from tests.stage3_helpers import session, span


def test_runtime_value_abi_exposes_injected_bar_context_and_metadata_exactly():
    """The ABI names are the compiler-facing projection of fixed context values."""
    runtime = session()
    frame = CallbackFrame(
        "HISTORICAL_EVAL",
        0,
        bar_index=7,
        is_last_bar=True,
        is_last_confirmed_history=True,
        last_bar_index=12,
    )
    tx = runtime.begin(
        frame,
        values=BarValues(
            10.0, 12.0, 9.0, 11.0, 42.0, 1_700_000_000_000, 1_700_000_900_000
        ),
    )

    assert is_na(runtime_values.na_v1(tx))
    assert {
        "open": runtime_values.open_v1(tx),
        "high": runtime_values.high_v1(tx),
        "low": runtime_values.low_v1(tx),
        "close": runtime_values.close_v1(tx),
        "volume": runtime_values.volume_v1(tx),
        "time": runtime_values.time_v1(tx),
        "time_close": runtime_values.time_close_v1(tx),
        "bar_index": runtime_values.bar_index_v1(tx),
        "last_bar_index": runtime_values.last_bar_index_v1(tx),
        "ticker": runtime_values.syminfo_ticker_v1(tx),
        "tickerid": runtime_values.syminfo_tickerid_v1(tx),
        "prefix": runtime_values.syminfo_prefix_v1(tx),
        "currency": runtime_values.syminfo_currency_v1(tx),
        "basecurrency": runtime_values.syminfo_basecurrency_v1(tx),
        "timezone": runtime_values.syminfo_timezone_v1(tx),
        "type": runtime_values.syminfo_type_v1(tx),
        "mintick": runtime_values.syminfo_mintick_v1(tx),
        "pointvalue": runtime_values.syminfo_pointvalue_v1(tx),
        "mincontract": runtime_values.syminfo_mincontract_v1(tx),
        "period": runtime_values.timeframe_period_v1(tx),
        "multiplier": runtime_values.timeframe_multiplier_v1(tx),
        "seconds": runtime_values.timeframe_in_seconds_v1(tx),
        "intraday": runtime_values.timeframe_isintraday_v1(tx),
        "daily": runtime_values.timeframe_isdaily_v1(tx),
        "weekly": runtime_values.timeframe_isweekly_v1(tx),
        "monthly": runtime_values.timeframe_ismonthly_v1(tx),
        "first": runtime_values.barstate_isfirst_v1(tx),
        "last": runtime_values.barstate_islast_v1(tx),
        "history": runtime_values.barstate_ishistory_v1(tx),
        "realtime": runtime_values.barstate_isrealtime_v1(tx),
        "new": runtime_values.barstate_isnew_v1(tx),
        "confirmed": runtime_values.barstate_isconfirmed_v1(tx),
        "last_confirmed_history": runtime_values.barstate_islastconfirmedhistory_v1(tx),
    } == {
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 42.0,
        "time": 1_700_000_000_000,
        "time_close": 1_700_000_900_000,
        "bar_index": 7,
        "last_bar_index": 12,
        "ticker": "BTCUSDT",
        "tickerid": "BINANCE:BTCUSDT",
        "prefix": "BINANCE",
        "currency": "USDT",
        "basecurrency": "BTC",
        "timezone": "UTC",
        "type": "crypto",
        "mintick": 0.01,
        "pointvalue": 1.0,
        "mincontract": 0.001,
        "period": "15",
        "multiplier": 15,
        "seconds": 900,
        "intraday": True,
        "daily": False,
        "weekly": False,
        "monthly": False,
        "first": False,
        "last": True,
        "history": True,
        "realtime": False,
        "new": True,
        "confirmed": True,
        "last_confirmed_history": True,
    }
    tx.commit()


def test_reference_abi_mutations_preserve_explicit_collection_invariants():
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    array = reference.array_new_v1(tx, "a", "int", 2, 3)
    reference.array_set_v1(tx, array, 1, 4)
    reference.array_unshift_v1(tx, array, 2)
    reference.array_insert_v1(tx, array, 2, 9)
    reference.array_push_v1(tx, array, 8)
    assert reference.array_size_v1(tx, array) == 5
    assert reference.array_get_v1(tx, array, 2) == 9
    assert reference.array_remove_v1(tx, array, 2) == 9
    assert reference.array_pop_v1(tx, array) == 8
    assert reference.array_shift_v1(tx, array) == 2
    reference.array_fill_v1(tx, array, 7, 1)
    assert reference.array_values_v1(tx, array) == (3, 7)
    assert reference.array_first_v1(tx, array) == 3
    assert reference.array_last_v1(tx, array) == 7
    assert reference.array_includes_v1(tx, array, 7)
    assert reference.array_indexof_v1(tx, array, 7) == 1
    assert reference.array_lastindexof_v1(tx, array, 7) == 1
    reference.array_reverse_v1(tx, array)
    reference.array_sort_v1(tx, array)
    copied = reference.array_copy_v1(tx, array, "a-copy")
    assert reference.array_values_v1(tx, copied) == (3, 7)
    reference.array_clear_v1(tx, copied)
    assert reference.array_size_v1(tx, copied) == 0

    mapping = reference.map_new_v1(tx, "m", "string,int")
    assert is_na(reference.map_put_v1(tx, mapping, "x", 1))
    assert is_na(reference.map_put_v1(tx, mapping, "y", 2))
    assert reference.map_contains_v1(tx, mapping, "x")
    assert reference.map_get_v1(tx, mapping, "y") == 2
    assert reference.array_values_v1(
        tx, reference.map_keys_v1(tx, mapping, "keys", "string")
    ) == ("x", "y")
    assert reference.array_values_v1(
        tx, reference.map_values_v1(tx, mapping, "values", "int")
    ) == (1, 2)
    copied_map = reference.map_copy_v1(tx, mapping, "m-copy")
    assert reference.map_size_v1(tx, copied_map) == 2
    assert reference.map_remove_v1(tx, copied_map, "x") == 1
    reference.map_put_all_v1(tx, copied_map, mapping)
    reference.map_clear_v1(tx, copied_map)
    assert reference.map_size_v1(tx, copied_map) == 0

    matrix = reference.matrix_new_v1(tx, "matrix", "int", 1, 2, 0)
    reference.matrix_set_v1(tx, matrix, 0, 1, 5)
    matrix_copy = reference.matrix_copy_v1(tx, matrix, "matrix-copy")
    assert (
        reference.matrix_rows_v1(tx, matrix_copy),
        reference.matrix_columns_v1(tx, matrix_copy),
    ) == (1, 2)
    assert reference.matrix_get_v1(tx, matrix_copy, 0, 1) == 5
    record = reference.udt_new_v1(tx, "record", "Pair", {"left": 1, "right": 0})
    reference.udt_set_v1(tx, record, "right", 2)
    record_copy = reference.udt_copy_v1(tx, record, "record-copy")
    assert reference.udt_get_v1(tx, record_copy, "right") == 2
    assert reference.enum_value_v1("side", "long", 0).member == "long"
    tx.commit()


def test_visual_abi_preserves_payloads_and_object_state_across_all_event_kinds():
    runtime = session()
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    source = span()
    events = [
        visual.plot_v1(tx, "plot", source, 1, title="P", linewidth=2, offset=3),
        visual.plotshape_v1(tx, "shape", source, True, title="S", text="buy"),
        visual.plotchar_v1(tx, "char", source, True, character="X"),
        visual.bgcolor_v1(tx, "bg", source, "red", show_last=2),
        visual.barcolor_v1(tx, "bar", source, "blue", editable=False),
        visual.hline_v1(tx, "hline", source, 5, linestyle="dotted"),
        visual.fill_v1(tx, "fill", source, "left", "right", fillgaps=False),
    ]
    line = visual.line_new_v1(tx, "line-new", source, "line", 0, 1, 2, 3, width=4)
    events.extend(
        [
            visual.line_set_xy1_v1(tx, "line-xy1", source, line, 4, 5),
            visual.line_set_xy2_v1(tx, "line-xy2", source, line, 6, 7),
            visual.line_delete_v1(tx, "line-delete", source, line),
        ]
    )
    label = visual.label_new_v1(tx, "label-new", source, "label", 1, 2, text="A")
    events.extend(
        [
            visual.label_set_text_v1(tx, "label-text", source, label, "B"),
            visual.label_delete_v1(tx, "label-delete", source, label),
        ]
    )
    assert [event.kind for event in events] == [
        "plot",
        "plotshape",
        "plotchar",
        "bgcolor",
        "barcolor",
        "hline",
        "fill",
        "line.set_xy1",
        "line.set_xy2",
        "line.delete",
        "label.set_text",
        "label.delete",
    ]
    assert tx.references.read_payload(line) == {
        "x1": 4,
        "y1": 5,
        "x2": 6,
        "y2": 7,
        "xloc": "bar_index",
        "extend": "none",
        "color": None,
        "style": "solid",
        "width": 4,
    }
    label_payload = tx.references.read_payload(label)
    assert isinstance(label_payload, dict)
    assert label_payload["text"] == "B"
    tx.commit()
    assert [event.kind for event in runtime.visuals.committed] == [
        "plot",
        "plotshape",
        "plotchar",
        "bgcolor",
        "barcolor",
        "hline",
        "fill",
        "line.new",
        "line.set_xy1",
        "line.set_xy2",
        "line.delete",
        "label.new",
        "label.set_text",
        "label.delete",
    ]


def test_ta_abi_edge_indicators_keep_known_monotonic_window_contracts():
    """Independent arithmetic expectations cover ABI entry points absent from the core pack."""
    runtime = session()
    final = None
    for index, value in enumerate(range(1, 7)):
        tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
        high, low = value + 1, value - 1
        final = {
            "mom": ta.mom_v1(tx, "mom", value, 3),
            "roc": ta.roc_v1(tx, "roc", value, 3),
            "cmo": ta.cmo_v1(tx, "cmo", value, 3),
            "stoch": ta.stoch_v1(tx, "stoch", value, high, low, 3),
            "tr": ta.tr_v1(tx, "tr", high, low, value),
            "atr": ta.atr_v1(tx, "atr", high, low, value, 3),
            "bbw": ta.bbw_v1(tx, "bbw", value, 3, 2.0),
            # Constant input avoids any assumption about EMA initialization policy.
            "kcw": ta.kcw_v1(tx, "kcw", 8.0, 9.0, 7.0, 8.0, 3, 2.0),
            "range": ta.range_v1(tx, "range", value, 3),
            "wpr": ta.wpr_v1(tx, "wpr", value, high, low, 3),
            "pivothigh": ta.pivothigh_v1(tx, "ph", value, 1, 1),
            "pivotlow": ta.pivotlow_v1(tx, "pl", value, 1, 1),
            "rising": ta.rising_v1(tx, "rising", value, 3),
            "falling": ta.falling_v1(tx, "falling", value, 3),
            "highestbars": ta.highestbars_v1(tx, "highestbars", value, 3),
            "lowestbars": ta.lowestbars_v1(tx, "lowestbars", value, 3),
            "dev": ta.dev_v1(tx, "dev", value, 3),
            "linear_percentile": ta.percentile_linear_interpolation_v1(
                tx, "pli", value, 3, 50.0
            ),
            "nearest_percentile": ta.percentile_nearest_rank_v1(
                tx, "pnr", value, 3, 50.0
            ),
        }
        tx.commit()
    assert final is not None
    assert final["mom"] == 3.0
    assert final["roc"] == final["cmo"] == 100.0
    assert final["stoch"] == 75.0
    assert final["tr"] == final["atr"] == final["range"] == 2.0
    # BB width = twice multiplier times population deviation / arithmetic mean.
    assert final["bbw"] == pytest.approx(2 * 2 * pstdev([4, 5, 6]) / mean([4, 5, 6]))
    # Constant basis 8 and true range 2: upper=12, lower=4, width/basis=1.
    assert final["kcw"] == (12 - 4) / 8
    assert final["wpr"] == -25.0
    assert is_na(final["pivothigh"]) and is_na(final["pivotlow"])
    assert final["rising"] is True and final["falling"] is False
    assert final["highestbars"] == 0 and final["lowestbars"] == -2
    assert final["dev"] == pytest.approx(2 / 3)
    assert final["linear_percentile"] == final["nearest_percentile"] == 5.0
