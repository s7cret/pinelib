"""CAT-04 numerical expected for array.binary_search* where the family is available.

Independent authority (not pinelib output):
- TradingView v6 Language Reference examples for
  array.binary_search / leftmost / rightmost on sorted [-2, 0, 1, 5, 9]
  and leftmost first-duplicate on [4, 5, 5, 5].
  https://www.tradingview.com/pine-script-reference/v6/
- March 2022 release notes added the family (v5 era), not v4:
  https://www.tradingview.com/pine-script-docs/release-notes/#march-2022
Producer admission for v4 is pine2ast tests/stage2/test_stage2_cat04_binary_search_authority.py.
"""

from __future__ import annotations

import pytest

from pinelib import CallbackFrame
from pinelib.abi import reference as ref
from tests.stage3_helpers import session

# TV docs: array.from(5, -2, 0, 9, 1) then array.sort -> [-2, 0, 1, 5, 9]
SORTED = [-2, 0, 1, 5, 9]


def _array(tx, values):
    dtype = "array<float>" if any(type(v) is float for v in values) else "array<int>"
    return tx.references.create("search", "array", dtype, list(values))


@pytest.mark.parametrize("version", [5, 6])
def test_tv_reference_sorted_example(version: int) -> None:
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    handle = _array(tx, SORTED)
    assert ref.array_binary_search_v1(tx, handle, 0) == 1
    assert ref.array_binary_search_leftmost_v1(tx, handle, 3) == 2
    assert ref.array_binary_search_rightmost_v1(tx, handle, 3) == 3
    assert ref.array_binary_search_v1(tx, handle, 3) == -1
    tx.abort()


@pytest.mark.parametrize("version", [5, 6])
def test_tv_reference_leftmost_duplicate_example(version: int) -> None:
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0, bar_index=0))
    handle = _array(tx, [4, 5, 5, 5])
    assert ref.array_binary_search_leftmost_v1(tx, handle, 5) == 1
    tx.abort()
