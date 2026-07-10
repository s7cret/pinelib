from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo
from pinelib.errors import PineRuntimeError
from pinelib.ta._impl_momentum import highest, lowest


def test_core_types_falls_back_when_marketdata_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_path = Path(__file__).resolve().parents[2] / "pinelib" / "core" / "types.py"
    module_name = "pinelib.core._phase0_types_fallback"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)

    original_import = builtins.__import__

    def fail_marketdata_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "marketdata_provider.contracts":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_marketdata_import)
    spec.loader.exec_module(module)

    assert module.parse_timeframe("1m").duration_ms == 60_000
    assert module.TimeframeInfo.from_string("1").interval_ms == 60_000


def test_timefunc_unknown_higher_timeframe_bucket_returns_none() -> None:
    runtime = PineRuntime(SymbolInfo("TEST:ABC"), TimeframeInfo.from_string("1"))
    runtime.begin_bar(Bar(time=0, open=1.0, high=2.0, low=0.5, close=1.5))

    assert runtime.timefunc._higher_timeframe_bucket("2H", runtime) is None


def test_runtime_extremes_require_stable_state_identifiers_and_lengths() -> None:
    runtime = PineRuntime(SymbolInfo("TEST:ABC"), TimeframeInfo.from_string("1"))
    runtime.begin_bar(Bar(time=0, open=1.0, high=2.0, low=0.5, close=1.5))

    with pytest.raises(PineRuntimeError, match="highest.*state_id"):
        highest(runtime.high, 2, runtime=runtime)
    assert highest(runtime.high, 2, runtime=runtime, state_id="highest") == 2.0
    with pytest.raises(PineRuntimeError, match="highest.*length"):
        highest(runtime.high, 3, runtime=runtime, state_id="highest")

    with pytest.raises(PineRuntimeError, match="lowest.*state_id"):
        lowest(runtime.low, 2, runtime=runtime)
    assert lowest(runtime.low, 2, runtime=runtime, state_id="lowest") == 0.5
    with pytest.raises(PineRuntimeError, match="lowest.*length"):
        lowest(runtime.low, 3, runtime=runtime, state_id="lowest")
