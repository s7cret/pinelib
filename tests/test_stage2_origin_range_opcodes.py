"""F2.3: for-range end evaluation must follow origin opcode, not session version.

Same-script control: ast2python test_dynamic_end_is_only_reevaluated_in_v6
(v5 fixed -> 2 iterations, v6 dynamic -> 3).
"""

from __future__ import annotations

from pinelib.abi import primitives
from tests.stage3_helpers import transaction


def _count(tx, primitive, *, mutate: bool) -> int:
    bound = [1]
    n = 0
    for _i in primitive(tx, 0, lambda: bound[0], 1):
        n += 1
        if mutate:
            bound[0] = 2
    return n


def test_fixed_end_does_not_reevaluate_inside_v6_session() -> None:
    _runtime, tx = transaction(version=6)
    assert _count(tx, primitives.range_fixed_end_v1, mutate=True) == 2
    tx.abort()


def test_dynamic_end_reevaluates_inside_v5_session() -> None:
    _runtime, tx = transaction(version=5)
    assert _count(tx, primitives.range_dynamic_end_v1, mutate=True) == 3
    tx.abort()


def test_session_range_still_follows_script_version() -> None:
    _, tx6 = transaction(version=6)
    assert _count(tx6, primitives.range_v1, mutate=True) == 3
    tx6.abort()
    _, tx5 = transaction(version=5)
    assert _count(tx5, primitives.range_v1, mutate=True) == 2
    tx5.abort()
