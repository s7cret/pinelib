from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pinelib.abi import input as input_abi
from pinelib.abi import math as math_abi
from pinelib.abi import metadata, string, time
from pinelib.core import is_na, na
from pinelib.errors import PineRuntimeError
from pinelib.input import InputRegistry, InputSpec
from pinelib.runtime import CallbackFrame, TimeframeContext
from pinelib.time import parse_session
from tests.stage3_helpers import language, session


def test_math_na_domains_rounding_and_varargs():
    assert is_na(math_abi.sqrt_v1(-1))
    assert is_na(math_abi.log_v1(0))
    assert is_na(math_abi.pow_v1(-2, 0.5))
    assert math_abi.round_v1(1.25, 1) == 1.3
    assert math_abi.round_v1(-1.25, 1) == -1.3
    assert math_abi.round_to_mintick_v1(1.225, 0.05) == pytest.approx(1.25)
    assert math_abi.avg_v1(1, 2, 3) == 2
    assert math_abi.max_v1(1, 3, 2) == 3
    assert is_na(math_abi.max_v1(1, na))
    with pytest.raises(PineRuntimeError):
        math_abi.avg_v1()
    assert is_na(math_abi.exp_v1(10000))


def test_string_surface_is_locale_independent_and_fail_closed():
    assert string.tostring_v1(1234.5, "#,##0.00") == "1,234.50"
    assert string.tostring_v1(0.125, "0.0%") == "12.5%"
    assert string.tostring_v1(1.234, "mintick", 0.01) == "1.23"
    assert string.format_v1("{{x}}={0,number,0.00}", 1.2) == "{x}=1.20"
    assert (
        string.format_time_v1(0, "yyyy-MM-dd HH:mm:ss", "UTC") == "1970-01-01 00:00:00"
    )
    assert string.replace_v1("a-a-a", "a", "x", 1) == "a-x-a"
    assert string.substring_v1("abc", 1) == "bc"
    assert is_na(string.tonumber_v1("not-a-number"))
    with pytest.raises(PineRuntimeError):
        string.substring_v1("abc", -1, 2)
    with pytest.raises(PineRuntimeError):
        string.format_v1("{9}", 1)
    with pytest.raises(PineRuntimeError):
        string.tostring_v1(1.2, "bad!")


def test_inputs_are_validated_and_immutable_after_admission():
    registry = InputRegistry(
        [InputSpec("x", "int", 1, 3, minimum=1, maximum=5, step=1)]
    )
    assert input_abi.int_v1(registry, "x") == 3
    with pytest.raises(AttributeError):
        registry.specs.append(InputSpec("y", "int", 1, 1))
    with pytest.raises(FrozenInstanceError):
        registry.specs[0].value = 4
    with pytest.raises(PineRuntimeError):
        InputSpec("x", "int", 1, 6, maximum=5)
    with pytest.raises(PineRuntimeError):
        InputSpec("x", "string", "a", "b", minimum=1)
    with pytest.raises(PineRuntimeError):
        InputRegistry([registry.specs[0], registry.specs[0]])
    assert InputRegistry(registry.specs).identity_hash == registry.identity_hash


def test_time_dst_calendar_session_and_version_default_days():
    before = time.timestamp_v1("America/New_York", 2024, 3, 10, 1, 30)
    after = time.timestamp_v1("America/New_York", 2024, 3, 10, 3, 30)
    assert after - before == 3_600_000
    assert time.dayofweek_v1(0, "UTC") == 5
    monday_noon = time.timestamp_v1("UTC", 2024, 1, 1, 12)
    assert time.in_session_v1(monday_noon, "0900-1700:2", "UTC", language())
    overnight = parse_session("2200-0200:2", language())
    tuesday_0100 = time.timestamp_v1("UTC", 2024, 1, 2, 1)
    assert overnight.contains(tuesday_0100, "UTC")
    saturday = time.timestamp_v1("UTC", 2024, 1, 6, 12)
    assert not parse_session("0000-0000", language(4)).contains(saturday, "UTC")
    assert parse_session("0000-0000", language(5)).contains(saturday, "UTC")
    with pytest.raises(PineRuntimeError):
        time.timestamp_v1("Missing/Zone", 2024, 1, 1)
    with pytest.raises(PineRuntimeError):
        parse_session("bad", language())


def test_metadata_reads_only_admitted_context_and_barstate():
    runtime = session()
    frame = CallbackFrame(
        "REALTIME_TICK", 0, True, False, bar_index=0, tick_index=0, is_last_bar=True
    )
    assert metadata.syminfo_tickerid_v1(runtime) == "BINANCE:BTCUSDT"
    assert metadata.timeframe_period_v1(runtime) == "15"
    assert metadata.timeframe_in_seconds_v1(runtime) == 900
    assert metadata.timeframe_isintraday_v1(runtime)
    assert metadata.barstate_isfirst_v1(runtime, frame)
    assert metadata.barstate_isnew_v1(runtime, frame)
    assert not metadata.barstate_isconfirmed_v1(runtime, frame)
    assert TimeframeContext.parse("1D").seconds == 86_400
    assert TimeframeContext.parse("1M").seconds is None
    with pytest.raises(PineRuntimeError):
        TimeframeContext.parse("0")
