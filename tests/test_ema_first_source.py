"""Primary EMA/MACD arithmetic and explicit numerical-state admission boundary."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from pinelib import CallbackFrame
from pinelib.abi import ta
from pinelib.core.values import na
from tests.stage3_helpers import session
from tests.test_rolling_statistics_state import assert_atomic, reseal

FIXTURES = Path(__file__).parent / 'fixtures'
MANUAL_BYTES = (FIXTURES / 'recursive_ta_manual_expected.json').read_bytes()
assert hashlib.sha256(MANUAL_BYTES).hexdigest() == '19b562cd1d7b37af215bbb300014b4e728b1efbce01cddf384fcc775ae2ced29'
MANUAL = json.loads(MANUAL_BYTES)
ELIGIBLE = [row for row in MANUAL['rows'] if row['expected'] is not None]
OLD = json.loads((FIXTURES / 'ema_first_source_v1_checkpoints.json').read_bytes())


def make(version, compact):
    runtime = session(version)
    runtime.commit_full_identity = not compact
    return runtime


def invoke(tx, name, value, parameters=None):
    params = parameters or ({'fast': 2, 'slow': 3, 'signal': 2} if name == 'macd' else {'length': 3})
    args = [params['fast'], params['slow'], params['signal']] if name == 'macd' else [params['length']]
    return getattr(ta, name + '_v1')(tx, 'sample', value, *args)


def equal(value, expected):
    if isinstance(expected, list):
        assert isinstance(value, tuple) and len(value) == len(expected)
        for item, want in zip(value, expected, strict=True):
            equal(item, want)
    elif expected['kind'] == 'na':
        assert value is na
    else:
        assert type(value) is float
        assert value == pytest.approx(float(expected['decimal_60']), rel=1e-12, abs=1e-12)


@pytest.mark.parametrize('row', ELIGIBLE, ids=lambda row: row['id'])
@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('route', ['historical', 'realtime', 'deferred_fill'])
def test_primary_complete_trajectory_and_lifecycle(row, version, compact, route):
    runtime = make(version, compact)
    sequence = 0
    deferred = route == 'deferred_fill'
    for bar, (source, expected) in enumerate(zip(row['source'], row['expected'], strict=True)):
        value = na if source == 'na' else float(source)

        def start(seq, final, phase=None):
            return runtime.begin(CallbackFrame(
                phase or ('REALTIME_TICK' if route == 'realtime' else 'HISTORICAL_EVAL'), seq,
                bar_index=bar, realtime=route == 'realtime', final_tick=final,
                defer_bar_commit=deferred))

        if route != 'historical':
            tx = start(sequence, False)
            invoke(tx, row['operation'], 99.0, row['parameters'])
            tx.commit()
            sequence += 1
            phase = 'ORDER_FILL_RECALC' if deferred else 'REALTIME_TICK'
            tx = start(sequence, False, phase)
            equal(invoke(tx, row['operation'], value, row['parameters']), expected)
            tx.abort()
            # The aborted callback sequence remains available for the exact retry.
            tx = start(sequence, False, phase)
            equal(invoke(tx, row['operation'], value, row['parameters']), expected)
            tx.commit()
            sequence += 1
        tx = start(sequence, True, 'ORDER_FILL_RECALC' if deferred else None)
        equal(invoke(tx, row['operation'], value, row['parameters']), expected)
        tx.commit()
        sequence += 1
        if deferred:
            runtime.finalize_bar(bar)
            sequence = runtime.sequence + 1
        saved = runtime.checkpoint().to_dict()
        slot = next(r for r in saved['state']['slots'] if r['owner'] == 'ta.' + row['operation'])
        if row['operation'] in {'ema', 'macd'}:
            assert slot['schema_version'] == 'ta.' + row['operation'] + '.state.v2'
            assert slot['working']['profile'] == 'ema_first_source_v1'
        clone = make(version, compact)
        clone.restore(json.loads(json.dumps(saved)))
        assert clone.checkpoint().to_dict() == saved
        runtime = clone


@pytest.mark.parametrize('case', OLD['cases'], ids=lambda c: f"{c['kind']}-{c['operation']}-{c['version']}-{c['compact']}")
def test_genuine_legacy_checkpoint_boundary(case):
    if case['kind'] == 'request':
        from tests.test_compiled_requests import Provider, runtime as request_runtime
        runtime = request_runtime(Provider(), case['version'])
        runtime.commit_full_identity = not case['compact']
        calls = runtime.requests.provider.calls
    else:
        runtime = make(case['version'], case['compact'])
    if case['version'] >= 5 and case['operation'] in {'ema', 'macd'}:
        assert_atomic(runtime, case['checkpoint'], 'replay.*original input')
    else:
        runtime.restore(case['checkpoint'])
        assert runtime.checkpoint().to_dict() == case['checkpoint']
        tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 4, bar_index=4))
        invoke(tx, case['operation'], 7.0)
        tx.commit()
        clone = make(case['version'], case['compact'])
        clone.restore(runtime.checkpoint().to_dict())
        assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()
    if case['kind'] == 'request':
        assert runtime.requests.provider.calls == calls


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
@pytest.mark.parametrize('portion', ['working', 'committed'])
@pytest.mark.parametrize('fault', ['extra', 'profile', 'missing_profile', 'kernel', 'schema', 'owner_schema',
                                  'owner', 'varip', 'parameter_bool', 'parameter_zero', 'parameter_extra',
                                  'value_bool', 'value_int', 'value_null', 'warmup', 'initial', 'partial'])
def test_resealed_state_shape_rejects_atomically(version, compact, name, portion, fault):
    runtime = make(version, compact)
    for bar in range(4):
        tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', bar, bar_index=bar))
        invoke(tx, name, float(bar + 1))
        tx.commit()
    saved = deepcopy(runtime.checkpoint().to_dict())
    row = saved['state']['slots'][0]
    state = row[portion]
    value_state = state if name == 'ema' else state['fast']
    param = 'length' if name == 'ema' else 'fast_length'
    if fault == 'extra':
        state['extra'] = 1
    elif fault == 'profile':
        state['profile'] = 'sma_seed'
    elif fault == 'missing_profile':
        state.pop('profile', None)
    elif fault == 'kernel':
        state['kernel'] = 'ta.rma'
    elif fault == 'schema':
        row['schema_version'] = 'ta.' + name + '.state.v99'
    elif fault == 'owner_schema':
        row['owner'], row['schema_version'] = 'custom.owner', 'ta.' + name + '.state.v99'
    elif fault == 'owner':
        row['owner'] = 'custom.owner'
    elif fault == 'varip':
        row['varip'] = True
    elif fault == 'parameter_bool':
        state['parameters'][param] = True
    elif fault == 'parameter_zero':
        state['parameters'][param] = 0
    elif fault == 'parameter_extra':
        state['parameters']['extra'] = 1
    elif fault == 'value_bool':
        value_state['value'] = True
    elif fault == 'value_int':
        value_state['value'] = 1
    elif fault == 'value_null':
        value_state['value'] = None
    elif fault == 'warmup':
        value_state['warmup'] = [1.0]
    elif fault == 'initial':
        row['committed_exists'] = False
    elif name == 'ema':
        state.pop('parameters')
    else:
        state['signal'] = {}
    assert_atomic(runtime, reseal(runtime, saved), 'EMA|MACD|moving.average')


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
def test_committed_seed_cannot_disappear_from_working_state(version, compact, name):
    runtime = make(version, compact)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    invoke(tx, name, 0.0)
    tx.commit()
    saved = runtime.checkpoint().to_dict()
    state = saved['state']['slots'][0]['working']
    if name == 'ema':
        state.pop('value')
    else:
        for key in ('fast', 'slow', 'signal'):
            state[key] = {}
    assert_atomic(runtime, reseal(runtime, saved), 'lost its seed')


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
@pytest.mark.parametrize('first', [0.0, 3.0])
def test_all_na_committed_then_first_defined_trial_roundtrip(version, compact, name, first):
    runtime = make(version, compact)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    actual = invoke(tx, name, na)
    assert actual is na if name == 'ema' else all(item is na for item in actual)
    tx.commit()
    tx = runtime.begin(CallbackFrame('REALTIME_TICK', 1, bar_index=1, realtime=True, final_tick=False))
    actual = invoke(tx, name, first)
    assert actual == (first if name == 'ema' else (0.0, 0.0, 0.0))
    tx.commit()
    saved = runtime.checkpoint().to_dict()
    row = saved['state']['slots'][0]
    assert 'value' not in (row['committed'] if name == 'ema' else row['committed']['fast'])
    clone = make(version, compact)
    clone.restore(json.loads(json.dumps(saved)))
    assert clone.checkpoint().to_dict() == saved
    for current in (runtime, clone):
        tx = current.begin(CallbackFrame('REALTIME_TICK', 2, bar_index=1, realtime=True))
        assert invoke(tx, name, first) == actual
        tx.commit()
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
def test_schema_rename_of_genuine_old_state_is_not_migration(version, compact, name):
    runtime = make(version, compact)
    old = next(c for c in OLD['cases'] if c['kind'] == 'native' and c['version'] == version
               and c['compact'] == compact and c['operation'] == name)
    saved = deepcopy(old['checkpoint'])
    saved['state']['slots'][0]['schema_version'] = 'ta.' + name + '.state.v2'
    assert_atomic(runtime, reseal(runtime, saved), 'EMA|MACD|moving.average')
