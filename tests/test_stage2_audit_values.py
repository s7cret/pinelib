"""Independent literal expectations for audit operator/nz/color boundaries."""
import pytest
from pinelib.core.values import pine_mod, pine_div_const_int, pine_nz, NZ_OMITTED, na
from pinelib.runtime.context import RuntimeLanguageContext
from pinelib.builtins.color import color_component
from pinelib.errors import PineRuntimeError


@pytest.mark.parametrize("left,right,expected", [(-5,2,1),(5,-2,-1),(-5,-2,-1),(5,2,1),(-5.5,2.0,0.5),(5.5,-2.0,-0.5)])
def test_modulo_literal_floor_values(left,right,expected):
    assert pine_mod(left,right) == expected


@pytest.mark.parametrize("left,right", [(na,2),(2,na)])
def test_modulo_na_is_not_transport_null(left,right):
    assert pine_mod(left,right) is na


@pytest.mark.parametrize("left,right", [(1,0),(1,0.0),(None,2),(2,None),(False,2),(2,True),(float("nan"),2)])
def test_modulo_rejects_invalid_native_values(left,right):
    with pytest.raises(PineRuntimeError):
        pine_mod(left,right)


@pytest.mark.parametrize("value", [None,False,"1",float("nan"),float("inf")])
def test_nz_float_rejects_invalid_native_values(value):
    with pytest.raises(PineRuntimeError):
        pine_nz(value,NZ_OMITTED,result_type="float",ctx=RuntimeLanguageContext(6, "audit-test", "pine-v6", "sha256:" + "0" * 64, "compiler_annotation"))


@pytest.mark.parametrize("value", ["#GGGGGG", "red", "#12345", None, 0])
def test_nz_color_rejects_invalid_native_values(value):
    with pytest.raises(PineRuntimeError):
        pine_nz(value,NZ_OMITTED,result_type="color",ctx=RuntimeLanguageContext(6, "audit-test", "pine-v6", "sha256:" + "0" * 64, "compiler_annotation"))


def test_nz_color_default_is_transparent_not_opaque_black():
    value=pine_nz(na,NZ_OMITTED,result_type="color",ctx=RuntimeLanguageContext(6, "audit-test", "pine-v6", "sha256:" + "0" * 64, "compiler_annotation"))
    assert value == "#00000000"
    assert color_component(value,"t") == 100.0


def test_nz_explicit_na_and_omission_are_different():
    ctx=RuntimeLanguageContext(6, "audit-test", "pine-v6", "sha256:" + "0" * 64, "compiler_annotation")
    assert pine_nz(na,na,result_type="int",ctx=ctx) is na
    assert pine_nz(na,NZ_OMITTED,result_type="int",ctx=ctx) == 0
