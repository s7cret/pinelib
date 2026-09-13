"""Additional finite-window and storage decoder cases with explicit identities."""

import pytest

from pinelib import CallbackFrame
from pinelib.core import is_na, na
from pinelib.core.values import pine_binary
from pinelib.errors import PineRuntimeError
from pinelib.reference.heap import PineEnumValue
from pinelib.ta import kernels as k
from tests.stage3_helpers import language, session
from tests.test_ta_contract_boundaries import run


@pytest.mark.parametrize("use_true_range", [False, True])
def test_constant_keltner_bands_do_not_depend_on_seed_convention(use_true_range):
    final = run(k.kc, [(8, 9, 7, 8)] * 5, 3, 2, use_true_range)[-1]
    assert tuple(final) == (8, 12, 4)
    missing = run(k.kc, [(8, na, 7, 8)] * 5, 3, 2, use_true_range)[-1]
    assert all(is_na(value) for value in missing)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_enum_binary_operator_rejects_unsupported_legacy_versions(version):
    value = PineEnumValue("side", "long", 0)
    with pytest.raises(PineRuntimeError, match="v5/v6"):
        pine_binary("==", value, value, language(version))


def test_tsi_profile_and_estimator_metadata_cannot_be_corrupted():
    rt = session()
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    k.tsi(tx, "tsi", 1, 2, 3)
    state = tx.state(
        "tsi", owner="ta.tsi", schema_version="ta.tsi.state.v2", initial={}
    )
    assert isinstance(state, dict)
    state["profile"] = "foreign"
    with pytest.raises(PineRuntimeError, match="profile"):
        k.tsi(tx, "tsi", 2, 2, 3)
    k.variance(tx, "variance", 1, 2)
    state = tx.state(
        "variance",
        owner="ta.variance",
        schema_version="ta.variance.state.v1",
        initial={},
    )
    assert isinstance(state, dict)
    state["parameters"] = {"biased": 1}
    with pytest.raises(PineRuntimeError, match="metadata"):
        k.variance(tx, "variance", 2, 2)
    tx.abort()


def test_scratch_state_rejects_series_key_name_disagreement():
    rt = session()
    tx = rt.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    tx.set_series("x", 1, "int")
    tx.commit()
    before = rt._state_json()
    wrong = dict(before, series={"foreign": before["series"]["x"]})
    with pytest.raises(PineRuntimeError, match="key/name"):
        rt._decode_runtime_state(wrong)
    assert rt._state_json() == before
