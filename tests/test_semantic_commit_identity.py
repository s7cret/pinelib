from __future__ import annotations

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession
from pinelib.errors import PineRuntimeError
from pinelib.events import SourceSpan
from pinelib.runtime.compact_transcript import CompactRuntimeTranscript
from pinelib.runtime.semantic import ALGORITHM
from pinelib.state.checkpoint import RuntimeCheckpoint
from pinelib.state.digest import AppendOnlyHistory


def session() -> RuntimeSession:
    result = RuntimeSession(
        RuntimeLanguageContext(
            6, "2026-08-29", "pine-v6", "sha256:" + "1" * 64, "compiler_annotation"
        )
    )
    result.commit_full_identity = False
    return result


def advance(
    s: RuntimeSession,
    index: int,
    price: float = 10.0,
    slot: object = 1,
    *,
    event: str = "plot",
    realtime: bool = False,
    final: bool = True,
):
    tx = s.begin(
        CallbackFrame(
            "REALTIME_TICK" if realtime else "HISTORICAL_EVAL",
            index,
            realtime,
            final,
            bar_index=index,
        )
    )
    tx.set_series("close", price)
    tx.set_slot("configuration", slot)
    tx.visual(
        kind=event,
        call_site_id="plot:1",
        payload={"value": price},
        source_span=SourceSpan("sha256:" + "2" * 64, "s.pine", 1, 1, 1, 8),
    )
    return tx.commit()


@pytest.mark.parametrize("difference", ["price", "slot", "event"])
def test_equal_revision_counts_are_not_equal_states(difference):
    first, second = session(), session()
    a = advance(first, 0)
    b = advance(
        second,
        0,
        price=11.0 if difference == "price" else 10.0,
        slot=[2, 3] if difference == "slot" else 1,
        event="fill" if difference == "event" else "plot",
    )
    assert a.revision_fingerprint == b.revision_fingerprint
    assert a.state_hash != b.state_hash
    assert a.state_hash_algorithm == ALGORITHM
    assert a.transcript_hash != b.transcript_hash


@pytest.mark.parametrize("realtime,final", [(False, True), (True, True), (True, False)])
def test_fast_checkpoint_resumes_as_uninterrupted(realtime, final):
    continuous = session()
    for index in range(3):
        advance(continuous, index, price=float(10 + index))
    advance(continuous, 3, realtime=realtime, final=final)
    checkpoint = continuous.checkpoint().to_dict()
    resumed = session()
    resumed.restore(checkpoint)
    assert resumed.checkpoint().to_dict() == checkpoint
    assert resumed.state_hash == continuous.state_hash
    assert resumed.semantic_state_hash == continuous.semantic_state_hash
    for index in range(4, 10):
        a, b = (
            advance(continuous, index, float(index)),
            advance(resumed, index, float(index)),
        )
        assert a == b
    assert resumed.checkpoint().to_dict() == continuous.checkpoint().to_dict()


def test_semantic_checkpoint_detects_resealed_payload_substitution_atomically():
    original = session()
    advance(original, 0)
    before = original.checkpoint().to_dict()
    changed = original.checkpoint().state
    changed["series"]["close"]["committed"][0] = 999
    changed["series"]["close"]["working"] = 999
    forged = RuntimeCheckpoint.seal(original.identity_hash, changed).to_dict()
    with pytest.raises(PineRuntimeError, match="state hash"):
        original.restore(forged)
    assert original.checkpoint().to_dict() == before


def test_committed_histories_do_not_leak_mutable_hashed_values():
    values = [{"items": [1]}]
    history = AppendOnlyHistory("test", values)
    expected = history.identity()
    values[0]["items"].append(2)
    history[0]["items"].append(3)
    for value in history:
        value["items"].clear()
    assert history == [{"items": [1]}]
    assert history.identity() == expected
    with pytest.raises(TypeError):
        history[0] = {"items": [99]}
    history.append({"items": [2]})
    assert history.identity() != expected


def test_committed_event_payload_is_detached_from_returned_event():
    runtime = session()
    advance(runtime, 0)
    before = runtime.semantic_state_hash
    runtime.visuals.committed[0].payload["value"] = 50
    runtime.transcript.entries[0]["state_hash"] = "sha256:" + "0" * 64
    assert runtime.semantic_state_hash == before
    restored = session()
    restored.restore(runtime.checkpoint().to_dict())


def test_fast_commit_avoids_historical_serialization(monkeypatch):
    runtime = session()
    advance(runtime, 0)

    def forbidden(*args, **kwargs):
        raise AssertionError("full historical serialization on the fast path")

    monkeypatch.setattr(runtime, "_state_json", forbidden)
    monkeypatch.setattr(type(runtime.series["close"]), "to_json", forbidden)
    monkeypatch.setattr(type(runtime.visuals), "to_json", forbidden)
    monkeypatch.setattr(type(runtime.alerts), "to_json", forbidden)
    monkeypatch.setattr(type(runtime.requests.registry), "to_json", forbidden)
    for index in range(1, 100):
        advance(runtime, index, float(index))
    assert len(runtime.transcript.entries) == 100


@pytest.mark.parametrize("entry", [None, 0, [], {}, {"sequence": False}])
def test_compact_transcript_rejects_malformed_entries(entry):
    trace = CompactRuntimeTranscript()
    with pytest.raises(PineRuntimeError):
        trace.append(entry)
    assert len(trace.entries) == 0


def test_cannot_relabel_identity_mid_run():
    runtime = session()
    advance(runtime, 0)
    runtime.commit_full_identity = True
    with pytest.raises(PineRuntimeError, match="immutable"):
        advance(runtime, 1)
    runtime.commit_full_identity = False
    assert runtime.sequence == 0
    advance(runtime, 1)
