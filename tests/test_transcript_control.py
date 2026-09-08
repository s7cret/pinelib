"""Control is bound by successful entries; legacy entries remain an exact prefix."""

from copy import deepcopy
import json

import pytest

from pinelib import CallbackFrame
from pinelib.errors import PineRuntimeError
from pinelib.runtime.compact_transcript import CompactRuntimeTranscript
from pinelib.runtime.transcript import RuntimeTranscript
from pinelib.state.checkpoint import RuntimeCheckpoint, sha
from tests.test_language_scopes_once import begin, session
from tests.test_varip_abort_checkpoint import reseal_pending


def make(version, compact):
    result = session(version)
    result.commit_full_identity = not compact
    return result


def as_legacy(runtime):
    state = deepcopy(runtime.checkpoint().state)
    transcript = RuntimeTranscript() if runtime.commit_full_identity else CompactRuntimeTranscript()
    for entry in state["transcript"]["entries"]:
        entry.pop("control", None)
        transcript.append(entry)
    state["transcript"] = transcript.to_dict()
    return RuntimeCheckpoint.seal(runtime.identity_hash, state, schema_version="1.0.0").to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_actual_publication_has_bound_control_independent_of_phase_string(version, compact):
    direct = make(version, compact)
    direct.begin(CallbackFrame("BAR_COMMIT", 0)).commit()
    entry = direct.transcript.entries[-1]
    assert entry["control"] == {"bar_commit_mode": "callback", "boundary": "callback"}
    assert not RuntimeTranscript.is_publication(entry)
    restored = make(version, compact)
    restored.restore(direct.checkpoint().to_dict())
    assert restored._last_published_bar is None and restored._deferred_mode is False
    deferred = make(version, compact)
    begin(deferred, 0, bar=0, deferred=True).commit()
    deferred.finalize_bar(0)
    assert deferred.transcript.entries[0]["control"] == {"bar_commit_mode": "deferred", "boundary": "callback"}
    assert deferred.transcript.entries[1]["control"] == {"bar_commit_mode": "deferred", "boundary": "bar_commit"}
    assert RuntimeTranscript.is_publication(deferred.transcript.entries[1])
    assert deferred.transcript.to_dict()["schema_version"] == ("2.1.0" if compact else "1.1.0")
    assert deferred.checkpoint().schema_version == "1.1.0"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_legacy_checkpoint_abort_then_retry_upgrades_only_new_success(version, compact):
    source = make(version, compact)
    tx = begin(source, 0)
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.commit()
    legacy = as_legacy(source)
    runtime = make(version, compact)
    runtime.restore(json.loads(json.dumps(legacy)))
    assert runtime.checkpoint().to_dict() == legacy
    tx = begin(runtime, 5, realtime=True)
    tx.write_scalar_v1("ticks", "varip", 1, "int")
    tx.abort()
    saved = runtime.checkpoint().to_dict()
    clone = make(version, compact)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    assert clone.transcript.to_dict() == legacy["state"]["transcript"]
    for current in (runtime, clone):
        tx = begin(current, 5, realtime=True)
        assert tx.declare_scalar_v1("ticks", "varip", lambda: None, "int") == 1
        tx.commit()
        assert current.transcript.entries[0] == legacy["state"]["transcript"]["entries"][0]
        assert current.transcript.entries[1]["control"] == {"bar_commit_mode": "callback", "boundary": "callback"}
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_pending_attempt_cannot_forge_established_mode_with_unchanged_transcript(version, compact, legacy):
    runtime = make(version, compact)
    tx = begin(runtime, 0)
    tx.declare_scalar_v1("ticks", "varip", lambda: 0, "int")
    tx.commit()
    if legacy:
        runtime.restore(as_legacy(runtime))
    tx = begin(runtime, 1, realtime=True)
    tx.write_scalar_v1("ticks", "varip", 1, "int")
    tx.abort()
    original = runtime.checkpoint().to_dict()
    forged = deepcopy(original["state"])
    forged["pending_abort"]["attempts"][-1]["frame"]["defer_bar_commit"] = True
    with pytest.raises(PineRuntimeError, match="bound control"):
        runtime.restore(reseal_pending(runtime, forged))
    assert runtime.checkpoint().to_dict() == original
    assert runtime._deferred_mode is False


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_first_deferred_provisional_success_binds_mode_before_any_publication(version, compact):
    runtime = make(version, compact)
    tx = begin(runtime, 0, bar=0, deferred=True)
    tx.declare_scalar_v1("ticks", "varip", lambda: 1, "int")
    tx.commit()
    tx = begin(runtime, 1, bar=0, deferred=True)
    tx.write_scalar_v1("ticks", "varip", 2, "int")
    tx.abort()
    saved = runtime.checkpoint().to_dict()
    assert len(runtime.transcript.entries) == 1
    assert runtime.transcript.entries[0]["control"]["bar_commit_mode"] == "deferred"
    clone = make(version, compact)
    clone.restore(saved)
    assert clone._deferred_mode is True and clone._last_published_bar is None
    for current in (runtime, clone):
        tx = begin(current, 1, bar=0, deferred=True)
        assert tx.declare_scalar_v1("ticks", "varip", lambda: None, "int") == 2
        tx.commit()
        current.finalize_bar(0)
    assert runtime.checkpoint().to_dict() == clone.checkpoint().to_dict()


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("corruption", ["downgrade_version", "legacy_after_control", "changed_mode", "extra_control", "null_control"])
def test_control_profile_rejects_resealed_entry_and_version_corruption(compact, corruption):
    runtime = make(6, compact)
    begin(runtime, 0).commit()
    begin(runtime, 1).commit()
    data = deepcopy(runtime.transcript.to_dict())
    if corruption == "downgrade_version": data["schema_version"] = "2.0.0" if compact else "1.0.0"
    elif corruption == "legacy_after_control": del data["entries"][-1]["control"]
    elif corruption == "changed_mode": data["entries"][-1]["control"]["bar_commit_mode"] = "deferred"
    elif corruption == "extra_control": data["entries"][-1]["control"]["forged"] = False
    elif corruption == "null_control": data["entries"][-1]["control"] = None
    if not compact:
        data["content_hash"] = sha({"entries": data["entries"]})
    # Compact decode also validates control before trusting the claimed chain.
    with pytest.raises(PineRuntimeError):
        RuntimeTranscript.from_dict(data)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("compact", [False, True])
def test_first_control_suffix_cannot_reinterpret_unchanged_legacy_mode(version, compact):
    from pinelib.state.digest import AppendOnlyHistory
    from pinelib.runtime.semantic import ALGORITHM
    runtime = make(version, compact)
    begin(runtime, 0).commit()
    legacy = as_legacy(runtime)
    runtime.restore(legacy)
    begin(runtime, 1).commit()
    data = deepcopy(runtime.transcript.to_dict())
    data["entries"][-1]["control"]["bar_commit_mode"] = "deferred"
    assert data["entries"][0] == legacy["state"]["transcript"]["entries"][0]
    data["content_hash"] = (sha({"schema_id": "openpine.runtime_transcript.v2", "state_hash_algorithm": ALGORITHM,
        "chain": AppendOnlyHistory("runtime-transcript-v2", data["entries"]).identity()}) if compact else
        sha({"entries": data["entries"]}))
    with pytest.raises(PineRuntimeError, match="legacy admission"):
        RuntimeTranscript.from_dict(data)


@pytest.mark.parametrize("compact", [False, True])
def test_pending_first_witness_must_match_preceding_provisional_bar(compact):
    runtime = make(6, compact)
    begin(runtime, 0, bar=0, deferred=True).commit()
    runtime.finalize_bar(0)
    begin(runtime, 2, bar=1, deferred=True).commit()
    with pytest.raises(PineRuntimeError, match="previous bar"):
        begin(runtime, 3, bar=2, deferred=True)
    begin(runtime, 3, bar=1, deferred=True).abort()
    original = runtime.checkpoint().to_dict()
    state = deepcopy(original["state"])
    state["pending_abort"]["attempts"][0]["frame"]["bar_index"] = 2
    with pytest.raises(PineRuntimeError, match="bound control"):
        runtime.restore(reseal_pending(runtime, state))
    assert runtime.checkpoint().to_dict() == original
