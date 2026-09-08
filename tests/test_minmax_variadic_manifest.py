"""Explicit repeated-source binding and unchanged numeric ABI controls."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from pinelib import na
from pinelib.abi import math as abi
from pinelib.abi.builder import build_manifest, check_manifest
from pinelib.abi.catalog import CATALOG
from pinelib.abi.manifest_v2_builder import _parameter_bindings
from pinelib.errors import PineRuntimeError


@pytest.fixture(scope="module")
def manifest():return build_manifest()


@pytest.mark.parametrize("name", ["min", "max"])
@pytest.mark.parametrize("version", range(1, 7))
def test_exact_modern_repeated_parameter_contract(manifest, name, version):
    symbol = "pine:function:math."+name
    row = next(r for r in manifest["rows"] if r["symbol_id"] == symbol)
    assert row["version_availability"] == [5, 6]
    assert (version in row["version_availability"]) is (version >= 5)
    assert row["producer_overload_ids"] == [symbol+"#canonical"]
    assert row["parameters"] == [{"name":"values", "qualifier_max":"series", "required":True,
                                   "type":"float", "variadic":True}]
    assert row["parameter_bindings"] == [{"abi_parameter":"values", "binding":"SOURCE_VARIADIC", "source":"values"}]
    assert row["abi_parameters"] == [{"name":"values", "position":0, "kind":"VAR_POSITIONAL", "has_default":False, "annotation":"object"}]
    assert row["state_model"] == "PURE" and row["evaluation_mode"] == "EAGER_ARGUMENTS"
    assert row["capabilities"] == ["value.numeric"]


def test_only_two_rows_change_without_other_denominator_or_contract_changes(manifest):
    remaining = deepcopy(manifest)
    remaining.pop("content_hash")
    selected = [r for r in remaining["rows"] if r["name"] in {"math.min","math.max"}]
    assert len(selected) == 2 and sum(len(r["version_availability"]) for r in selected) == 4
    remaining["rows"] = [r for r in remaining["rows"] if r not in selected]
    encoded = json.dumps(remaining,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == "f93148868ada8979df7095ceff7f423e481792123a9ed4ab0f6e9f516569e76c"
    check_manifest(Path(__file__).parents[1]/"pinelib/abi/target_manifest.json")


@pytest.mark.parametrize("name", ["min", "max"])
def test_legacy_global_catalog_and_versionless_callable_are_not_replaced(manifest, name):
    legacy = next(r for r in CATALOG if r.symbol_id == "pine:function:"+name)
    modern = next(r for r in CATALOG if r.symbol_id == "pine:function:math."+name)
    assert legacy.pine_versions == (1,2,3,4) and legacy.call_form == "global_function"
    assert modern.pine_versions == (5,6) and modern.call_form == "namespace_function"
    assert legacy.abi_callable == modern.abi_callable == "pinelib.abi.math."+name+"_v1"
    assert legacy.state_model == modern.state_model == "PURE"
    assert not any(r["name"] in {name,"math."+name} for r in manifest["historical_call_bindings"])
    signature = inspect.signature(getattr(abi,name+"_v1"))
    assert list(signature.parameters) == ["values"]
    assert signature.parameters["values"].kind is inspect.Parameter.VAR_POSITIONAL


@pytest.mark.parametrize("name", ["math.min", "math.max"])
@pytest.mark.parametrize("fault", [None,"missing_flag","false_flag","numeric_flag","fixed_abi","keyword_abi","other_name","method","other_source"])
def test_spread_requires_exact_audited_source_and_abi_shapes(name, fault):
    official = {"name":name,"category":"functions","parameters":[{"name":"values","variadic":True}]}
    parameters = [{"name":"values","kind":"VAR_POSITIONAL","has_default":False}]
    if fault == "missing_flag":official["parameters"][0].pop("variadic")
    elif fault == "false_flag":official["parameters"][0]["variadic"] = False
    elif fault == "numeric_flag":official["parameters"][0]["variadic"] = 1
    elif fault == "fixed_abi":parameters[0]["kind"] = "POSITIONAL_OR_KEYWORD"
    elif fault == "keyword_abi":parameters[0]["kind"] = "VAR_KEYWORD"
    elif fault == "other_name":official["name"] = "math.avg"
    elif fault == "method":official["category"] = "methods"
    elif fault == "other_source":
        official["parameters"][0]["name"] = "items"
        parameters[0]["name"] = "items"
    rows = _parameter_bindings(official, parameters)
    assert len(rows) == 1
    assert rows[0]["binding"] == ("SOURCE_VARIADIC" if fault is None else "SOURCE_PARAMETER")


@pytest.mark.parametrize("name,expected", [("min",-7),("max",10)])
def test_existing_numeric_owner_uses_all_arguments_and_exact_ints(name, expected):
    values = (4,10,2,-7,5)
    result = getattr(abi,name+"_v1")(*values)
    assert type(result) is int and result == expected
    assert values == (4,10,2,-7,5)


@pytest.mark.parametrize("name,expected", [("min",-2.5),("max",3.25)])
def test_existing_float_extrema_and_one_argument_control(name, expected):
    function = getattr(abi,name+"_v1")
    result = function(1.5,-2.5,3.25,0.0)
    assert type(result) is float and result == expected
    assert function(-8) == -8 and type(function(-8)) is int
    assert function(2.5) == 2.5 and type(function(2.5)) is float


@pytest.mark.parametrize("name", ["min", "max"])
@pytest.mark.parametrize("position", [0,1,3])
def test_existing_canonical_na_propagates_from_every_argument_position(name, position):
    values = [4,2,3]
    values.insert(position,na)
    assert getattr(abi,name+"_v1")(*values) is na


@pytest.mark.parametrize("name", ["min", "max"])
@pytest.mark.parametrize("bad", [False,True,None,"1",float("inf"),float("nan")])
@pytest.mark.parametrize("position", [0,3])
def test_existing_bad_numeric_values_are_not_coerced_or_truncated(name, bad, position):
    values = [4,2,3]
    values.insert(position,bad)
    with pytest.raises(PineRuntimeError):getattr(abi,name+"_v1")(*values)


@pytest.mark.parametrize("name", ["min", "max"])
def test_existing_empty_and_keyword_abi_rejection_remains(name):
    function = getattr(abi,name+"_v1")
    with pytest.raises(PineRuntimeError,match="at least one"):function()
    with pytest.raises(TypeError):function(values=1)
