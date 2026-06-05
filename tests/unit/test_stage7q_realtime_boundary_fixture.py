from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo
from pinelib.core.types import TickUpdate

WORKSPACE_ENV = os.environ.get("PINELIB_TV_FIXTURE_WORKSPACE")
WORKSPACE = Path(WORKSPACE_ENV).expanduser() if WORKSPACE_ENV else None
FIXTURE = (
    WORKSPACE
    / "tv_strategy_oracle/realtime_probe/stage7j_to_9g_next50_2026-04-30"
    / "stage7k_du_sequence_fixture_v3.json"
) if WORKSPACE else None


def _runtime() -> PineRuntime:
    return PineRuntime(SymbolInfo("BINANCE:BTCUSDT"), TimeframeInfo.from_string("5"))


def test_stage7i_boundary_fixture_varip_accumulates_intrabar_and_can_reset_on_new_bar() -> None:
    if FIXTURE is None or not FIXTURE.exists():
        pytest.skip(f"optional TradingView boundary fixture not found: {FIXTURE}")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    boundary = next(row for row in data["rows"] if row["timeSec"] == data["boundary"]["timeSec"])

    rt = _runtime()
    rt.begin_realtime_bar(
        Bar(
            time=boundary["timeSec"] * 1000,
            time_close=(boundary["timeSec"] + 300) * 1000,
            open=boundary["duCloseFirst"],
            high=max(boundary["duCloseFirst"], boundary["duCloseLast"]),
            low=min(boundary["duCloseFirst"], boundary["duCloseLast"]),
            close=boundary["duCloseFirst"],
            volume=0,
        )
    )

    counter = rt.get_varip_state("stage7i_tick_counter", lambda: {"ticks": 0})
    assert isinstance(counter, dict)
    ticks = (
        (boundary["tickFirst"], boundary["duCloseFirst"]),
        (boundary["tickLast"], boundary["duCloseLast"]),
    )
    for tick_no, price in ticks:
        rt.update_realtime_tick(
            TickUpdate(price=price, time=boundary["timeSec"] * 1000 + int(tick_no))
        )
        counter["ticks"] = int(tick_no)

    assert counter["ticks"] == 161
    assert rt.close.current == boundary["chartClose"]
    assert rt.barstate.isrealtime is True
    assert rt.barstate.isconfirmed is False

    rt.end_bar()
    rt.reset_varip_state()
    next_time = data["boundary"]["nextTimeSec"] * 1000
    rt.begin_realtime_bar(
        Bar(
            time=next_time,
            time_close=next_time + 300_000,
            open=boundary["duCloseLast"],
            high=boundary["duCloseLast"],
            low=boundary["duCloseLast"],
            close=boundary["duCloseLast"],
        )
    )
    assert rt.get_varip_state("stage7i_tick_counter", lambda: {"ticks": 0})["ticks"] == 0
