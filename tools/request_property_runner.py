from __future__ import annotations

import json
import random
from dataclasses import replace

from pinelib import CallbackFrame, is_na
from pinelib.request import (
    DataFinality,
    GapsMode,
    LookaheadMode,
    RequestKind,
    ResultShape,
)
from pinelib.request.alignment import align_lower_timeframe, align_security
from tests.stage4_helpers import bars, provider_for, query, request_session

SEED = 4004
rng = random.Random(SEED)
shape = ResultShape.scalar("float")
case_count = 0


def expression(bar, _context):
    return bar.number("close")


def discover(q, values, *, finalities=None):
    source = bars(q, values, finalities=finalities)
    provider = provider_for(q, source)
    runtime = request_session(provider)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    if q.kind == RequestKind.SECURITY:
        tx.requests.security(
            q,
            expression,
            shape,
            chart_open_ms=0,
            chart_close_ms=max(1, len(source)) * q.timeframe_seconds * 1000,
        )
    else:
        tx.requests.security_lower_tf(
            q,
            expression,
            shape,
            chart_open_ms=0,
            chart_close_ms=max(2, len(source)) * q.timeframe_seconds * 1000,
        )
    tx.commit()
    dataset = runtime.requests.registry.lookup(
        q.discovery_identity(shape), committed_only=True
    )
    assert dataset is not None
    return dataset


def slow_security(dataset, chart_open, chart_close, realtime, allow_developing):
    q = dataset.key.query
    rows = dataset.evaluated_bars
    selected = -1
    updated = False
    if realtime:
        candidates = [i for i, row in enumerate(rows) if row.open_time_ms < chart_close]
        if candidates:
            candidate = candidates[-1]
            row = rows[candidate]
            if row.close_time_ms > chart_open and (
                row.finality == DataFinality.FINAL or allow_developing
            ):
                selected = candidate
                updated = True
        if selected < 0:
            candidates = [
                i
                for i, row in enumerate(rows)
                if row.close_time_ms <= chart_close
                and row.finality == DataFinality.FINAL
            ]
            if candidates:
                selected = candidates[-1]
                row = rows[selected]
                updated = chart_open < row.close_time_ms <= chart_close
    elif q.lookahead == LookaheadMode.OFF:
        candidates = [
            i
            for i, row in enumerate(rows)
            if row.close_time_ms <= chart_close and row.finality == DataFinality.FINAL
        ]
        if candidates:
            selected = candidates[-1]
            row = rows[selected]
            updated = chart_open < row.close_time_ms <= chart_close
    else:
        candidates = [
            i
            for i, row in enumerate(rows)
            if row.open_time_ms < chart_close and row.finality == DataFinality.FINAL
        ]
        if candidates:
            selected = candidates[-1]
            row = rows[selected]
            updated = chart_open <= row.open_time_ms < chart_close
    developing_gap = (
        selected >= 0
        and realtime
        and q.gaps == GapsMode.ON
        and rows[selected].finality != DataFinality.FINAL
    )
    if selected < 0 or developing_gap or (q.gaps == GapsMode.ON and not updated):
        return None, selected
    return dataset.value(selected), selected


# Four HTF modes, historical and realtime, including one developing terminal bar.
for gaps in (GapsMode.OFF, GapsMode.ON):
    for lookahead in (LookaheadMode.OFF, LookaheadMode.ON):
        q = query(
            timeframe="60",
            snapshot_id=f"property:{gaps.value}:{lookahead.value}",
            expression_context_id=f"property-call:{gaps.value}:{lookahead.value}",
            gaps=gaps,
            lookahead=lookahead,
        )
        dataset = discover(
            q,
            tuple(float(i) for i in range(12)),
            finalities=(DataFinality.FINAL,) * 11 + (DataFinality.DEVELOPING,),
        )
        for _ in range(400):
            opening = rng.randrange(0, 48) * 15 * 60_000
            closing = opening + rng.choice((15, 30, 45, 60)) * 60_000
            realtime = bool(rng.getrandbits(1))
            allow = bool(rng.getrandbits(1))
            actual, cursor = align_security(
                dataset,
                chart_open_ms=opening,
                chart_close_ms=closing,
                realtime=realtime,
                allow_developing_realtime=allow,
            )
            expected, selected = slow_security(
                dataset, opening, closing, realtime, allow
            )
            if expected is None:
                assert is_na(actual)
            else:
                assert actual == expected
            assert cursor.selected_start == selected == cursor.selected_end
            case_count += 1

# LTF full-containment model.
lq = query(
    kind=RequestKind.SECURITY_LOWER_TF,
    timeframe="5",
    snapshot_id="property:lower",
    expression_context_id="property-lower-call",
)
lower = discover(
    lq,
    tuple(float(i) for i in range(144)),
    finalities=(DataFinality.FINAL,) * 143 + (DataFinality.DEVELOPING,),
)
for _ in range(800):
    opening = rng.randrange(0, 132) * 5 * 60_000
    closing = opening + rng.choice((15, 30, 60)) * 60_000
    realtime = bool(rng.getrandbits(1))
    allow = bool(rng.getrandbits(1))
    actual, cursor = align_lower_timeframe(
        lower,
        chart_open_ms=opening,
        chart_close_ms=closing,
        realtime=realtime,
        allow_developing_realtime=allow,
        max_intrabars=1000,
    )
    expected_indexes = [
        i
        for i, row in enumerate(lower.evaluated_bars)
        if row.open_time_ms >= opening
        and row.close_time_ms <= closing
        and (row.finality == DataFinality.FINAL or (realtime and allow))
    ]
    assert actual == tuple(lower.value(i) for i in expected_indexes)
    assert cursor.selected_start == (expected_indexes[0] if expected_indexes else -1)
    assert cursor.selected_end == (expected_indexes[-1] if expected_indexes else -1)
    case_count += 1

# Semantic identity mutations must not collide.
base = query(snapshot_id="property:identity")
seen = {base.content_hash}
for index in range(1000):
    candidate = replace(
        base,
        snapshot_id=f"property:identity:{index}",
        expression_context_id=f"property:call:{rng.randrange(1_000_000_000)}",
        expression_id=f"property:expr:{rng.randrange(1_000_000_000)}",
        calc_bars_count=(index % 100) + 1,
        dynamic=bool(index % 2),
    )
    assert candidate.content_hash not in seen
    seen.add(candidate.content_hash)
    assert candidate.discovery_identity(shape) != base.discovery_identity(shape)
    case_count += 1

print(
    json.dumps(
        {
            "schema_id": "pinelib.stage4.request_property_result.v1",
            "seed": SEED,
            "cases": case_count,
            "failures": 0,
            "pass": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
