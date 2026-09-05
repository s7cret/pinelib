"""A successful callback releases outputs; only the host publishes a chart bar."""

import pytest

from pinelib import CallbackFrame
from pinelib.errors import PineRuntimeError
from pinelib.runtime.metadata import BarValues
from tests.stage3_helpers import session


def execute(
    s, bar, *, price=10.0, phase="HISTORICAL_EVAL", realtime=False, final=True, tick=0
):
    frame = CallbackFrame(
        phase,
        s.sequence + 1,
        realtime,
        final,
        bar_index=bar,
        tick_index=tick,
        last_bar_index=2,
        is_last_bar=bar == 2,
        is_last_confirmed_history=bar == 1,
        defer_bar_commit=True,
    )
    tx = s.begin(
        frame,
        values=BarValues(
            price, price, price, price, 1, bar * 60000, bar * 60000 + 59999
        ),
    )
    history = tx.value_close if bar == 0 else s.series["close"].read(1)
    ordinary = tx.state("v", owner="test", schema_version="1", initial=0) + 1
    persistent = (
        tx.state("ip", owner="test", schema_version="1", initial=0, varip=True) + 1
    )
    tx.set_slot("v", ordinary, owner="test")
    tx.set_slot("ip", persistent, owner="test", varip=True)
    flags = s.barstate(frame)
    tx.commit()
    return history, ordinary, persistent, flags


@pytest.mark.parametrize("full_identity", [False, True])
def test_recalculations_do_not_advance_history_and_var_rolls_back(full_identity):
    s = session()
    s.commit_full_identity = full_identity
    assert execute(s, 0, price=10)[:3] == (10, 1, 1)
    assert len(s.series["close"].committed) == 0
    s.finalize_bar(0)
    assert execute(s, 1, price=20, phase="ORDER_FILL_RECALC")[:3] == (10, 2, 2)
    assert execute(s, 1, price=21)[:3] == (10, 2, 3)
    assert execute(s, 1, price=22, phase="ORDER_FILL_RECALC")[:3] == (10, 2, 4)
    assert list(s.series["close"].committed) == [10]
    s.finalize_bar(1)
    assert list(s.series["close"].committed) == [10, 22]
    with pytest.raises(PineRuntimeError):
        s.finalize_bar(1)
    with pytest.raises(PineRuntimeError, match="published"):
        execute(s, 1)


@pytest.mark.parametrize("full_identity", [False, True])
def test_realtime_rolls_back_var_preserves_varip_and_publishes_final_tick(
    full_identity,
):
    s = session()
    s.commit_full_identity = full_identity
    execute(s, 0)
    s.finalize_bar(0)
    execute(s, 1, price=20)
    s.finalize_bar(1)
    a = execute(s, 2, price=30, realtime=True, final=False, phase="REALTIME_EVAL")
    assert a[:3] == (20, 3, 3)
    assert a[3].isnew and not a[3].isconfirmed and a[3].islast
    with pytest.raises(PineRuntimeError, match="unconfirmed"):
        s.finalize_bar(2)
    b = execute(
        s, 2, price=31, realtime=True, final=False, phase="ORDER_FILL_RECALC", tick=0
    )
    assert b[:3] == (20, 3, 4)
    assert b[3].isnew  # callback ordinal is not a tick ordinal
    c = execute(
        s, 2, price=32, realtime=True, final=True, phase="REALTIME_EVAL", tick=1
    )
    assert c[:3] == (20, 3, 5)
    assert not c[3].isnew and c[3].isconfirmed
    s.finalize_bar(2)
    assert list(s.series["close"].committed) == [10, 20, 32]


@pytest.mark.parametrize("full_identity", [False, True])
def test_only_published_boundary_is_checkpointable_and_resumes_identically(
    full_identity,
):
    s = session()
    s.commit_full_identity = full_identity
    execute(s, 0)
    with pytest.raises(PineRuntimeError):
        s.checkpoint()
    with pytest.raises(PineRuntimeError, match="previous bar"):
        execute(s, 1)
    s.finalize_bar(0)
    restored = session()
    restored.commit_full_identity = full_identity
    restored.restore(s.checkpoint().to_dict())
    for runtime in (s, restored):
        execute(runtime, 1, price=11, phase="ORDER_FILL_RECALC")
        execute(runtime, 1, price=12)
        runtime.finalize_bar(1)
    assert restored.checkpoint().to_dict() == s.checkpoint().to_dict()
    assert restored.semantic_state_hash == s.semantic_state_hash


def test_host_cannot_switch_commit_mode_mid_run():
    s = session()
    execute(s, 0)
    s.finalize_bar(0)
    with pytest.raises(PineRuntimeError, match="mode"):
        s.begin(CallbackFrame("HISTORICAL_EVAL", s.sequence + 1, bar_index=1))


def test_scalar_initializer_is_lazy_and_assignment_is_in_bar_history():
    runtime=session()
    initialized=[]
    def initial():
        initialized.append(1)
        return 0
    for bar in range(3):
        tx=runtime.begin(CallbackFrame("HISTORICAL_EVAL",runtime.sequence+1,bar_index=bar,defer_bar_commit=True))
        old=tx.declare_scalar_v1("scalar-test","var",initial,"int")
        tx.write_scalar_v1("scalar-test","var",old+1,"int")
        tx.commit()
        runtime.finalize_bar(bar)
    assert initialized == [1]
    assert list(runtime.series["scalar-test"].committed) == [1,2,3]


def test_scalar_api_rejects_unknown_lifetime_instead_of_resetting_it():
    runtime=session()
    tx=runtime.begin(CallbackFrame("HISTORICAL_EVAL",0))
    with pytest.raises(PineRuntimeError,match="unsupported scalar"):
        tx.declare_scalar_v1("x","once",lambda: 0,"int")
    tx.abort()
