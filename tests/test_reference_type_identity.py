"""Native and host-created references must have the same comparison identity."""
import json
from copy import deepcopy

import pytest

from pinelib import CallbackFrame
from pinelib.abi import reference as ref
from pinelib.errors import PineRuntimeError
from pinelib.reference.heap import ReferenceHandle
from tests.stage3_helpers import session


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('dtype', ['int', 'float', 'array<int>', 'array<float>'])
@pytest.mark.parametrize('side,expected', [('leftmost', 2), ('rightmost', 3)])
def test_native_factory_and_full_descriptor_search_same_neighbor(version, dtype, side, expected):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    handle = ref.array_new_v1(tx, 'search', dtype)
    for value in [-2, 0, 1, 5, 9]:
        ref.array_push_v1(tx, handle, value)
    before = deepcopy(tx.references.to_json())
    assert getattr(ref, 'array_binary_search_' + side + '_v1')(tx, handle, 3) == expected
    assert tx.references.to_json() == before
    assert tx.references.type_descriptor(handle) == dtype
    assert tx.references.normalized_type_descriptor(handle) in {'array<int>', 'array<float>'}


@pytest.mark.parametrize('kind,element,payload', [('array', 'float', [1.]), ('matrix', 'float', {'rows': 1, 'columns': 1, 'values': [1.]}), ('map', 'string,float', [['a', 1.]])])
@pytest.mark.parametrize('wrapped', [False, True])
def test_canonical_view_keeps_wire_representation_and_existing_binding(kind, element, payload, wrapped):
    runtime = session(6)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    canonical = kind + '<' + element + '>'
    descriptor = canonical if wrapped else element
    handle = tx.references.create('object', kind, descriptor, payload)
    assert tx.references.normalized_type_descriptor(handle) == canonical
    tx.declare_reference_v1('r', 'var', lambda: handle, canonical)
    tx.commit()
    checkpoint = json.loads(json.dumps(runtime.checkpoint().to_dict()))
    restored = session(6)
    restored.restore(checkpoint)
    assert restored.references.type_descriptor(handle) == descriptor
    assert restored.references.normalized_type_descriptor(handle) == canonical
    assert restored.checkpoint().to_dict() == checkpoint


@pytest.mark.parametrize('dtype', ['float', 'array<float>'])
@pytest.mark.parametrize('compact', [False, True])
def test_alias_copy_slice_retry_and_checkpoint_preserve_normalized_type(dtype, compact):
    runtime = session(6)
    runtime.commit_full_identity = not compact
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    original = ref.array_new_v1(tx, 'original', dtype)
    for item in [-10., -2., 0., 4., 9.]:
        ref.array_push_v1(tx, original, item)
    copy = ref.array_copy_v1(tx, original, 'copy')
    view = ref.array_slice_v1(tx, original, 1, 4, 'slice')
    tx.commit()
    checkpoint = runtime.checkpoint().to_dict()
    tx = runtime.begin(CallbackFrame('REALTIME_TICK', 1, bar_index=1, realtime=True, final_tick=False))
    assert ref.array_binary_search_leftmost_v1(tx, original, 2.) == 2
    assert ref.array_binary_search_leftmost_v1(tx, copy, 2.) == 2
    assert ref.array_binary_search_leftmost_v1(tx, view, 2.) == 1
    assert ref.array_binary_search_rightmost_v1(tx, view, 2.) == 2
    tx.abort()
    assert runtime.checkpoint().to_dict() == checkpoint
    restored = session(6)
    restored.commit_full_identity = not compact
    restored.restore(json.loads(json.dumps(checkpoint)))
    assert restored.references.normalized_type_descriptor(view) == 'array<float>'
    assert restored.references.type_descriptor(view) == dtype


def test_normalization_does_not_validate_forged_or_unknown_handles():
    runtime = session(6)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    ref.array_new_v1(tx, 'a', 'float')
    for handle in [ReferenceHandle('missing', 'array'), ReferenceHandle('a', 'matrix'), {'object_id': 'a', 'kind': 'array'}]:
        with pytest.raises(PineRuntimeError):
            tx.references.normalized_type_descriptor(handle)


@pytest.mark.parametrize('version', [1, 2, 3, 4])
@pytest.mark.parametrize('dtype', ['float', 'array<float>'])
def test_canonical_identity_does_not_change_legacy_search_policy(version, dtype):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    handle = ref.array_new_v1(tx, 'search', dtype)
    for item in [1., 5., 9.]:
        ref.array_push_v1(tx, handle, item)
    # This is the legacy engine policy, NOT evidence of TradingView v4 availability.
    assert ref.array_binary_search_leftmost_v1(tx, handle, 3.) == -1
    assert ref.array_binary_search_rightmost_v1(tx, handle, 3.) == -1


@pytest.mark.parametrize('dtype,values,query', [('string', ['a', 'c'], 'b'), ('bool', [False, True], 0.5)])
def test_non_numeric_descriptors_do_not_acquire_numeric_neighbor_fallback(dtype, values, query):
    runtime = session(6)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    handle = ref.array_new_v1(tx, 'search', dtype)
    for item in values:
        ref.array_push_v1(tx, handle, item)
    assert ref.array_binary_search_leftmost_v1(tx, handle, query) == -1
