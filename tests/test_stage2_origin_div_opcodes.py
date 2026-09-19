"""F2.2: operator.div.legacy/fractional must not follow session pine_version.

Catalog: v5 TRUNCATE, v6 FRACTIONAL. Mixed import lowers to origin opcode;
collapsing both opcodes onto operator_binary_v1 made a v6 session execute
v5 library `a / b` as 2.5.
"""

from __future__ import annotations

from pinelib.abi import primitives
from tests.stage3_helpers import transaction


def test_legacy_div_truncates_inside_v6_session() -> None:
    _runtime, tx = transaction(version=6)
    assert primitives.operator_div_legacy_v1(tx, "/", 5, 2) == 2
    assert type(primitives.operator_div_legacy_v1(tx, "/", 5, 2)) is int
    tx.abort()


def test_fractional_div_is_float_inside_v5_session() -> None:
    _runtime, tx = transaction(version=5)
    assert primitives.operator_div_fractional_v1(tx, "/", 5, 2) == 2.5
    tx.abort()


def test_session_binary_div_still_follows_script_version() -> None:
    _, tx6 = transaction(version=6)
    assert primitives.operator_binary_v1(tx6, "/", 5, 2) == 2.5
    tx6.abort()
    _, tx5 = transaction(version=5)
    assert primitives.operator_binary_v1(tx5, "/", 5, 2) == 2
    tx5.abort()
