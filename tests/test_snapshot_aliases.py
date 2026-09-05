"""Only explicit canonical/venue names are aliases; ambiguity is an error."""

from dataclasses import replace

import pytest
from pinelib.errors import PineRuntimeError
from pinelib.request.provider import RequestProviderError
from pinelib.request.snapshots import SnapshotRequestProvider

from tests.test_compiled_requests import Provider


def test_both_explicit_names_return_the_identical_source():
    p = Provider()
    source = p.source("EX:S", "5")
    assert p.source("stock:S", "5") is source
    assert p.source("EX:S", "5") is source
    # No bare-ticker guessing or unannounced case folding.
    for name in ("S", "ex:s", "EX:T"):
        with pytest.raises(RequestProviderError):
            p.source(name, "5")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("overlap", ["canonical", "venue"])
def test_alias_collision_rejected_in_either_insertion_order(reverse, overlap):
    first = Provider().source("EX:S", "5")
    # First's canonical ID used as another venue alias, or first's venue alias
    # reused for another instrument; neither is an admissible second source.
    other = replace(
        first,
        instrument=replace(
            first.instrument,
            tickerid=first.instrument_id
            if overlap == "canonical"
            else first.instrument.tickerid,
        ),
    )
    sources = (first, other) if not reverse else (other, first)
    with pytest.raises(PineRuntimeError, match="ambiguous"):
        SnapshotRequestProvider(sources)


def test_equal_canonical_and_venue_id_is_a_single_unambiguous_alias():
    source = Provider().source("EX:S", "5")
    source = replace(
        source, instrument=replace(source.instrument, tickerid=source.instrument_id)
    )
    assert SnapshotRequestProvider((source,)).source("stock:S", "5") is source
