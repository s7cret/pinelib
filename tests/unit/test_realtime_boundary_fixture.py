from __future__ import annotations

from pinelib import Bar, PineRuntime, SymbolInfo, TimeframeInfo
from pinelib.core.types import TickUpdate

_BOUNDARY_FIXTURE = {
    "boundary": {"timeSec": 1_777_000_000, "nextTimeSec": 1_777_000_300},
    "rows": [
        {
            "timeSec": 1_777_000_000,
            "tickFirst": 1,
            "tickLast": 161,
            "duCloseFirst": 75_000.0,
            "duCloseLast": 75_123.5,
            "chartClose": 75_123.5,
        }
    ],
}


def _runtime() -> PineRuntime:
    return PineRuntime(SymbolInfo("BINANCE:BTCUSDT"), TimeframeInfo.from_string("5"))


def test_realtime_boundary_fixture_varip_accumulates_intrabar_and_can_reset_on_new_bar() -> None:
    data = _BOUNDARY_FIXTURE
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

    counter = rt.get_varip_state("realtime_tick_counter", lambda: {"ticks": 0})
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
    assert rt.get_varip_state("realtime_tick_counter", lambda: {"ticks": 0})["ticks"] == 0
