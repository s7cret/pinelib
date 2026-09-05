"""Segments, not their container, own portable NA decoding during restore."""

import json

import pytest

from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, is_na, na


def runtime(compact):
    obj = RuntimeSession(
        RuntimeLanguageContext(
            6, "test", "pine-v6", "sha256:" + "a" * 64, "compiler_annotation"
        )
    )
    obj.commit_full_identity = not compact
    return obj


@pytest.mark.parametrize("compact", [True, False])
def test_na_series_is_decoded_once_and_roundtrips(compact):
    obj = runtime(compact)
    for i, value in enumerate((na, na, 3.0)):
        tx = obj.begin(CallbackFrame("HISTORICAL_EVAL", i, bar_index=i))
        tx.set_series("na-series", value, "float")
        tx.commit()
    state = json.loads(json.dumps(obj.checkpoint().to_dict()))
    restored = runtime(compact)
    restored.restore(state)
    assert restored.checkpoint().to_dict() == state
    assert is_na(restored.series["na-series"].committed[0])
    assert obj.state_hash == restored.state_hash


@pytest.mark.parametrize("compact", [True, False])
def test_equal_callback_counts_with_different_values_do_not_collide(compact):
    left, right = runtime(compact), runtime(compact)
    for obj, value in ((left, 3.0), (right, 7.0)):
        tx = obj.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
        tx.set_series("same-name", value, "float")
        tx.commit()
    assert left.state_hash != right.state_hash
    assert left.semantic_state_hash != right.semantic_state_hash
