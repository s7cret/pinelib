import json
from pathlib import Path

from openpine_contracts import IntentKind, validate_payload

from pinelib.strategy.intent_tape import IntentTape

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "intent_tape_cancel_all.json"


def test_intent_tape_golden_cancel_all() -> None:
    tape = IntentTape(
        run_id="run-g",
        strategy_id="strat-g",
        producer_commit="deadbeef",
        phase="score",
    )
    event = tape.record(IntentKind.CANCEL_ALL, command_id="all", bar_index=0)
    validate_payload("openpine.intent.v2", event)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert event == expected
