"""Semantic state root without repeated committed-history serialization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pinelib.state.checkpoint import sha

if TYPE_CHECKING:
    from pinelib.events import AlertTape, VisualTape
    from pinelib.reference import RuntimeReferenceHeap
    from pinelib.request import RequestEngine
    from pinelib.state.series import SeriesStorage
    from pinelib.state.slots import StateSlotRegistry

ALGORITHM = "pinelib.semantic-state.merkle.v1"


def semantic_state_digest(
    identity: str,
    sequence: int,
    series: Mapping[str, SeriesStorage[object]],
    slots: StateSlotRegistry,
    references: RuntimeReferenceHeap,
    visuals: VisualTape,
    alerts: AlertTape,
    requests: RequestEngine,
) -> str:
    return sha(
        {
            "algorithm": ALGORITHM,
            "identity": identity,
            "sequence": sequence,
            "series": {
                key: value.semantic_hash for key, value in sorted(series.items())
            },
            "slots": sha(slots.to_json()),
            "references": sha(references.to_json()),
            "visuals": visuals.semantic_hash,
            "alerts": alerts.semantic_hash,
            "requests": requests.semantic_hash,
        }
    )
