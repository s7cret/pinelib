"""Only the modern TSI length parameter metadata changes; ABI and other rows stay exact."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from pinelib.abi import ta
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.manifest_v2_builder import _audited_signature

FIXTURES = Path(__file__).with_name('fixtures')
LITERAL = FIXTURES / 'recursive_length_literal_metadata.json'
EXPECTED = json.loads(LITERAL.read_bytes())
SCOPE = json.loads((FIXTURES / 'recursive_length_scope.json').read_bytes())


@pytest.fixture(scope='module')
def manifest():
    return build_manifest()


@pytest.mark.parametrize('version', range(1, 7))
def test_exact_tsi_row_and_versions(manifest, version):
    row = next(row for row in manifest['rows'] if row['name'] == 'ta.tsi')
    assert row == EXPECTED['expected_tsi_row']
    assert (version in row['version_availability']) is (version >= 5)


def test_whole_remainder_and_precomputed_manifest_identity(manifest):
    remaining = deepcopy(manifest)
    remaining.pop('content_hash')
    remaining['rows'] = [row for row in remaining['rows'] if row['name'] != 'ta.tsi']
    assert len(remaining['rows']) == EXPECTED['expected_other_rows'] == 1107
    encoded = json.dumps(remaining, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == SCOPE['target_remainder_without_tsi_sha256']
    assert manifest['content_hash'] == EXPECTED['expected_content_hash']
    check_manifest(Path(__file__).parents[1] / 'pinelib/abi/target_manifest.json')


@pytest.mark.parametrize('category', ['methods', 'variables', 'constants', 'types'])
@pytest.mark.parametrize('name', ['ta.tsi', 'tsi'])
def test_override_is_restricted_to_the_modern_function(category, name):
    original = {'name': name, 'category': category, 'parameters': [{'name': 'short_length', 'qualifier_max': 'series'}], 'returns': 'preserved'}
    assert _audited_signature(deepcopy(original)) == original


@pytest.mark.parametrize('name', ['tsi', 'ta.other'])
def test_other_function_names_are_not_inferred(name):
    original = {'name': name, 'category': 'functions', 'parameters': [{'name': 'long_length', 'qualifier_max': 'series'}], 'returns': 'preserved'}
    assert _audited_signature(deepcopy(original)) == original


def test_tsi_abi_parameter_order_and_required_arguments_remain():
    parameters = inspect.signature(ta.tsi_v1).parameters
    assert list(parameters) == ['tx', 'state_id', 'source', 'short_length', 'long_length']
    assert all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and p.default is inspect.Parameter.empty for p in parameters.values())


def test_literal_metadata_was_frozen_before_generator_execution():
    assert hashlib.sha256(LITERAL.read_bytes()).hexdigest() == '76a18219703bec025598e0c7af2cbd7fc0f4b860c75b14386a0eef3222b93b00'
