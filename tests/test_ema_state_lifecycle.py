"""EMA seed state survives real owner rollback and nested request admission."""

from copy import deepcopy
import json

import pytest

from pinelib import CallbackFrame
from pinelib.abi.compiled_request import CompiledRequestExpression, security_v1
from pinelib.core.values import na
from pinelib.request import ResultShape
from pinelib.state.checkpoint import RuntimeCheckpoint
from tests.test_compiled_requests import Provider, begin, runtime as request_runtime
from tests.test_ema_first_source import invoke, make
from tests.test_nominal_registry_request_restore import checkpoint_with
from tests.test_rolling_statistics_state import assert_atomic, reseal
from tests.test_varip_abort_checkpoint import reseal_pending


def pending(runtime, name):
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    invoke(tx, name, 3.0)
    tx.declare_scalar_v1('ticks', 'varip', lambda: 0, 'int')
    tx.commit()
    baseline = runtime.checkpoint().to_dict()
    tx = runtime.begin(CallbackFrame('REALTIME_TICK', 1, bar_index=1, realtime=True, final_tick=False))
    invoke(tx, name, -1.0)
    tx.write_scalar_v1('ticks', 'varip', 1, 'int')
    tx.abort()
    assert runtime.transcript.to_dict() == baseline['state']['transcript']
    return baseline, runtime.checkpoint().to_dict()


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
@pytest.mark.parametrize('location', ['attempted', 'successful', 'post'])
@pytest.mark.parametrize('fault', ['legacy', 'profile', 'typed_value'])
def test_pending_proof_validates_every_state_before_atomic_swap(version, compact, name, location, fault):
    runtime = make(version, compact)
    baseline_saved, saved = pending(runtime, name)
    assert saved['schema_version'] == '1.1.0'
    clone = make(version, compact)
    clone.restore(json.loads(json.dumps(saved)))
    assert clone.checkpoint().to_dict() == saved
    forged = deepcopy(saved)
    record = forged['state']['pending_abort']
    segment = (record['attempts'][0]['attempted_state'] if location == 'attempted' else
               record['successful_state'] if location == 'successful' else forged['state'])
    row = next(row for row in segment['slots'] if row['owner'] == 'ta.' + name)
    if fault == 'legacy':
        row['schema_version'] = 'ta.' + name + '.state.v1'
    elif fault == 'profile':
        row['working']['profile'] = 'sma_seed'
    else:
        value = row['working'] if name == 'ema' else row['working']['fast']
        value['value'] = True
    if location == 'successful':
        baseline = make(version, compact)
        baseline.restore(baseline_saved)
        changed = {**deepcopy(baseline_saved), 'state': {
            **segment, 'transcript': baseline_saved['state']['transcript']}}
        changed = reseal(baseline, changed)
        forged['state']['transcript'] = changed['state']['transcript']
        record['transcript_hash'] = changed['state']['transcript']['content_hash']
    assert_atomic(runtime, reseal_pending(runtime, forged['state']), 'EMA|MACD|replay.*original input')
    # The attempted -1 never entered the successful history. Exact retry seed is 3.
    for current in (runtime, clone):
        tx = current.begin(CallbackFrame('REALTIME_TICK', 1, bar_index=1, realtime=True))
        result = invoke(tx, name, 5.0)
        expected = 4.0 if name == 'ema' else (1 / 3, 2 / 9, 1 / 9)
        assert result == pytest.approx(expected)
        tx.commit()
        assert 'pending_abort' not in current.checkpoint().state
    assert clone.checkpoint().to_dict() == runtime.checkpoint().to_dict()


class MovingAverageChild:
    evaluations = 0

    def __init__(self, runtime):
        self.runtime = runtime

    def ema(self):
        MovingAverageChild.evaluations += 1
        return invoke(self.runtime, 'ema', self.runtime.value_close)

    def macd(self):
        MovingAverageChild.evaluations += 1
        return invoke(self.runtime, 'macd', self.runtime.value_close)[0]


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
@pytest.mark.parametrize('pending_child', [False, True])
@pytest.mark.parametrize('fault', [None, 'legacy', 'profile', 'typed_value'])
def test_actual_compiled_child_and_late_rejection_without_execution(version, compact, name, pending_child, fault):
    parent = request_runtime(Provider(), version)
    parent.commit_full_identity = not compact
    tx = begin(parent, 0)
    children = {}
    for index in range(2):
        identity = 'sha256:' + ('e' if index == 0 else 'f') * 64
        expression = CompiledRequestExpression(tx, MovingAverageChild, name, identity, ResultShape.scalar('float'))
        security_v1(tx, 'EX:S', '5', expression, 'site-' + str(index))
        children[identity] = expression._runtime
    tx.commit()
    # Corrupt the last serialized child so a preceding valid scratch decode occurs.
    identity = parent.checkpoint().state['requests']['registry']['datasets'][-1]['key']['query']['expression_id']
    child = children[identity]
    if pending_child:
        trial = child.begin(CallbackFrame('REALTIME_TICK', child.sequence + 1,
                                          bar_index=2, realtime=True, final_tick=False))
        trial.declare_scalar_v1('ticks', 'varip', lambda: 0, 'int')
        trial.write_scalar_v1('ticks', 'varip', 1, 'int')
        invoke(trial, name, 99.0)
        trial.abort()
    saved = child.checkpoint().to_dict()
    if fault is not None:
        segment = (saved['state']['pending_abort']['attempts'][0]['attempted_state']
                   if pending_child else saved['state'])
        row = next(row for row in segment['slots'] if row['owner'] == 'ta.' + name)
        if fault == 'legacy':
            row['schema_version'] = 'ta.' + name + '.state.v1'
        elif fault == 'profile':
            row['working']['profile'] = 'sma_seed'
        else:
            part = row['working'] if name == 'ema' else row['working']['signal']
            part['value'] = True
        saved = reseal_pending(child, saved['state']) if pending_child else reseal(child, saved)
    checkpoint = checkpoint_with(parent, saved, identity=identity)
    calls, evaluations = parent.requests.provider.calls, MovingAverageChild.evaluations
    if fault is None:
        parent.restore(json.loads(json.dumps(checkpoint)))
        assert parent.checkpoint().to_dict() == checkpoint
    else:
        assert_atomic(parent, checkpoint, 'EMA|MACD|replay.*original input')
    assert parent.requests.provider.calls == calls
    assert MovingAverageChild.evaluations == evaluations


@pytest.mark.parametrize('version', [1, 2, 3, 4])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
def test_modern_slot_revision_is_rejected_in_earlier_language(version, compact, name):
    runtime = make(version, compact)
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    invoke(tx, name, 3.0)
    tx.commit()
    saved = runtime.checkpoint().to_dict()
    saved['state']['slots'][0]['schema_version'] = 'ta.' + name + '.state.v2'
    assert_atomic(runtime, reseal(runtime, saved), 'revision differs from Pine version')


@pytest.mark.parametrize('version', [5, 6])
@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('name', ['ema', 'macd'])
def test_all_na_first_attempt_abort_does_not_create_numerical_history(version, compact, name):
    runtime = make(version, compact)
    before = runtime.checkpoint().to_dict()
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    result = invoke(tx, name, na)
    assert result is na if name == 'ema' else all(item is na for item in result)
    tx.abort()
    saved = runtime.checkpoint().to_dict()
    expected = deepcopy(before)
    if compact:
        # Exact empty format transition performed by the preexisting begin owner.
        expected['state']['transcript'] = {
            'schema_id': 'openpine.runtime_transcript.v2', 'schema_version': '2.0.0',
            'state_hash_algorithm': 'pinelib.semantic-state.merkle.v1', 'entries': [],
            'content_hash': 'sha256:ccfdaa541e18a849a9127b43fa665c984ea7877b10e147d055f56fd2ff2acce0'}
        expected = RuntimeCheckpoint.seal(runtime.identity_hash, expected['state']).to_dict()
    assert saved == expected
    assert runtime.slots.to_json() == []
    clone = make(version, compact)
    clone.restore(saved)
    assert clone.checkpoint().to_dict() == saved
    # With the selected format established, another abort is byte-identical.
    tx = runtime.begin(CallbackFrame('HISTORICAL_EVAL', 0, bar_index=0))
    invoke(tx, name, na)
    tx.abort()
    assert runtime.checkpoint().to_dict() == saved
