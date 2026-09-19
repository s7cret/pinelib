"""History ABI restoration must preserve the sealed audit endpoint exactly."""
from copy import deepcopy
import json
from importlib.resources import files

import pytest

from tests.stage2_audit_repair_helpers import digest, restore_history_restoration


def current():
    return json.loads(files('pinelib.abi').joinpath('target_manifest.json').read_text())


def reseal(value):
    value['content_hash'] = digest({k: v for k, v in value.items() if k != 'content_hash'})
    return value


def test_history_restoration_preserves_rows_and_previous_endpoint():
    value = current()
    before = restore_history_restoration(value)
    lock = json.loads(files('pinelib.abi').joinpath('stage2_audit_repair_delta_lock.json').read_text())
    assert before['content_hash'] == lock['artifacts']['target_manifest.json']['after_content_hash']
    assert before['rows'] == value['rows']
    assert 'compiled_history_reservation' not in before
    assert value == current()


@pytest.mark.parametrize('part', ['rows', 'contract', 'operation', 'hash'])
def test_history_restoration_rejects_tampering_even_when_resealed(part):
    value = deepcopy(current())
    if part == 'rows':
        value['rows'][0]['name'] = 'forged'
    elif part == 'contract':
        value['compiled_history_reservation']['supported_pine_versions'] = [1, 2, 3]
    elif part == 'operation':
        row = next(r for r in value['compiler_operations'] if r['name'] == 'state.reserve_history.v1')
        row['abi_callable'] = 'forged.callable'
    else:
        value['content_hash'] = 'sha256:' + '0' * 64
    if part != 'hash':
        reseal(value)
    with pytest.raises((AssertionError, ValueError)):
        restore_history_restoration(value)
