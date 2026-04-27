from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pinelib.core.types import RuntimeConfig
from pinelib.errors import PineRuntimeError

VisualKind = Literal["label", "line", "box", "table"]


@dataclass(frozen=True, slots=True)
class PineObjectId:
    kind: VisualKind
    value: int


@dataclass(slots=True)
class VisualEvent:
    action: str
    object_id: PineObjectId
    attrs: dict[str, Any] = field(default_factory=dict)


class VisualRecorder:
    """Deterministic recorder for Pine visual object lifecycle events.

    This is intentionally not a renderer. Generated Pine code can allocate objects,
    update fields, and delete them while tests or downstream adapters inspect a
    stable event log and current object table.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        *,
        max_labels_count: int | None = None,
        max_lines_count: int | None = None,
        max_boxes_count: int | None = None,
        max_tables_count: int | None = None,
    ) -> None:
        self.config = config
        self.max_counts: dict[VisualKind, int | None] = {
            "label": max_labels_count,
            "line": max_lines_count,
            "box": max_boxes_count,
            "table": max_tables_count,
        }
        self._next_id = 1
        self.objects: dict[PineObjectId, dict[str, Any]] = {}
        self.events: list[VisualEvent] = []

    def new(self, kind: VisualKind, **attrs: Any) -> PineObjectId:
        self._check_limit(kind)
        object_id = PineObjectId(kind, self._next_id)
        self._next_id += 1
        self.objects[object_id] = dict(attrs)
        self.events.append(VisualEvent("new", object_id, dict(attrs)))
        return object_id

    def set(self, object_id: PineObjectId, **attrs: Any) -> None:
        if object_id not in self.objects:
            raise PineRuntimeError(f"Unknown or deleted Pine object id {object_id.kind}:{object_id.value}")
        self.objects[object_id].update(attrs)
        self.events.append(VisualEvent("set", object_id, dict(attrs)))

    def delete(self, object_id: PineObjectId) -> None:
        if object_id in self.objects:
            del self.objects[object_id]
            self.events.append(VisualEvent("delete", object_id, {}))

    def label_new(self, **attrs: Any) -> PineObjectId:
        return self.new("label", **attrs)

    def line_new(self, **attrs: Any) -> PineObjectId:
        return self.new("line", **attrs)

    def box_new(self, **attrs: Any) -> PineObjectId:
        return self.new("box", **attrs)

    def table_new(self, **attrs: Any) -> PineObjectId:
        return self.new("table", **attrs)

    def _check_limit(self, kind: VisualKind) -> None:
        limit = self.max_counts.get(kind)
        if limit is None:
            return
        active = sum(1 for object_id in self.objects if object_id.kind == kind)
        if active >= limit:
            raise PineRuntimeError(f"Maximum {kind} object count exceeded: {limit}")
