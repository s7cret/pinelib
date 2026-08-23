import json
from pathlib import Path

from openpine_contracts import IntentKind, validate_payload

from pinelib.strategy.intent_tape import IntentTape
from tests.rc4_fixtures import execution_context, known_source_span

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "intent_tape_cancel_all.json"


def test_intent_tape_golden_cancel_all() -> None:
    tape = IntentTape(
        run_id="run-g",
        strategy_id="strat-g",
        series_id="series-g",
        instrument_id="TEST:GOLDEN",
        timeframe="60",
        producer_commit="801b908e0ba53d1387cfd032cb6d29aa53ba0ca0",
        strict_production=True,
        execution_context=execution_context(
            run_id="run-g",
            strategy_id="strat-g",
            series_id="series-g",
            instrument_id="TEST:GOLDEN",
            exchange="TEST",
            market="stock",
            symbol="GOLDEN",
            timeframe="60",
        ),
    )
    tape.begin_callback(
        bar_index=0,
        bar_open_time_utc_ms=0,
        phase="BAR_COMMIT",
        recalc_iteration=0,
    )
    event = tape.record(
        IntentKind.CANCEL_ALL,
        command_id="all",
        source_span=known_source_span(),
    )
    validate_payload("openpine.intent.v2", event)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert event == expected
