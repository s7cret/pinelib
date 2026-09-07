"""Evidence for a completed abort without changing the successful transcript."""

from dataclasses import replace

from pinelib.errors import PL_CHECKPOINT_INVALID, PineRuntimeError
from pinelib.state.checkpoint import clone_runtime_value


class AbortBaseline:
    """Capture mutable values without serializing append-only histories.

    This object lives for one callback. Histories cannot grow on its abort path;
    successful callbacks discard it. The portable evidence is built only on abort.
    """

    def __init__(self, runtime):
        self.sequence = runtime.sequence
        self.deferred_mode = runtime._deferred_mode
        self.pending_bar_frame = runtime._pending_bar_frame
        self.pending_abort = runtime._pending_abort
        self.attempt_bytes = runtime._pending_abort_attempt_bytes
        self.last_published_bar = runtime._last_published_bar
        self.machine_state = runtime.machine.state
        self.identity_mode = runtime._identity_mode
        self.transcript = runtime.transcript
        self.request_state = runtime.requests.__dict__.copy()
        self.request_registry_state = runtime.requests.registry.__dict__.copy()
        self.series = {key: replace(value, working=clone_runtime_value(value.working))
                       for key, value in runtime.series.items()}
        self.slots = runtime.slots.to_json()
        self.references = runtime.references.to_json()
        self.visuals = [event.to_dict() for event in runtime.visuals.working]
        self.alerts = [event.to_dict() for event in runtime.alerts.working]

    def materialize(self, runtime):
        return {
            "sequence": self.sequence,
            "series": {key: value.to_json() for key, value in sorted(self.series.items())},
            "slots": self.slots,
            "references": self.references,
            "visuals": {"committed": runtime.visuals.to_json()["committed"], "working": self.visuals},
            "alerts": {"committed": runtime.alerts.to_json()["committed"], "working": self.alerts},
            "requests": runtime.requests.to_json(),
        }

    def restore_rejected_attempt(self, runtime):
        """Restore exact preattempt state when its witness exceeds the budget.

        Decode before updating any live owner. Keep provider/evaluator caches and
        owner identities; no callback or provider execution is involved.
        """
        restored = runtime._decode_runtime_state(self.materialize(runtime))
        runtime.series.clear()
        runtime.series.update(self.series)
        for name in ("slots", "references", "visuals", "alerts"):
            getattr(runtime, name).__dict__.update(getattr(restored, name).__dict__)
        runtime.requests.__dict__.update(self.request_state)
        runtime.requests.registry.__dict__.update(self.request_registry_state)
        runtime.sequence = self.sequence
        runtime._deferred_mode = self.deferred_mode
        runtime._pending_bar_frame = self.pending_bar_frame
        runtime._pending_abort = self.pending_abort
        runtime._pending_abort_attempt_bytes = self.attempt_bytes
        runtime._last_published_bar = self.last_published_bar
        runtime.machine.state = self.machine_state
        runtime._identity_mode = self.identity_mode
        runtime.transcript = self.transcript
        runtime._active = None


def _require(condition, detail):
    if not condition:
        raise PineRuntimeError("pending abort " + detail, code=PL_CHECKPOINT_INVALID)


def validate_abort_attempt(projected, attempted, new_series, frame):
    """Validate mutations between real begin and abort owner projections.

    Working values may change during a callback. Declaration identities and all
    committed baselines may not. The enclosing replay performs the actual rollback.
    """
    before, after = projected._state_json(), attempted._state_json()
    _require(before["sequence"] == after["sequence"], "changed successful sequence")
    _require(before["requests"] == after["requests"], "changed committed requests")
    for name in ("visuals", "alerts"):
        _require(before[name]["committed"] == after[name]["committed"], "changed event history")
        for event in after[name]["working"]:
            _require(event["sequence"] == frame.sequence and event["phase"] == frame.phase,
                     "working event differs from attempted frame")

    old_series, new_rows = before["series"], after["series"]
    _require(set(old_series) <= set(new_rows), "lost an existing series")
    _require(type(new_series) is list and all(type(name) is str for name in new_series)
             and new_series == sorted(set(new_rows) - set(old_series)),
             "new series declaration list differs from attempted allocations")
    for key, old in old_series.items():
        _require(all(new_rows[key].get(field) == value for field, value in old.items()
                     if field not in ("working", "evaluated")), "changed series history or declaration")
    for key in new_series:
        row = new_rows[key]
        _require(not row["committed"] and row["revision"] == 0 and row["initialized"] is True,
                 "introduced committed series state")

    old_slots = {row["state_id"]: row for row in before["slots"]}
    new_slots = {row["state_id"]: row for row in after["slots"]}
    _require(set(old_slots) <= set(new_slots), "lost a retained slot")
    for key, old in old_slots.items():
        _require(all(new_slots[key][field] == old[field] for field in old if field != "working"),
                 "changed committed slot or declaration")
    for key, row in new_slots.items():
        if key not in old_slots:
            _require(not row["committed_exists"], "introduced committed slot state")

    old_objects = {row["object_id"]: row for row in before["references"]["objects"]}
    objects = {row["object_id"]: row for row in after["references"]["objects"]}
    _require(set(old_objects) <= set(objects), "lost a retained heap object")
    for key, old in old_objects.items():
        new = objects[key]
        for field in ("object_id", "kind", "type_descriptor", "udt_schema", "committed",
                      "committed_revision", "committed_exists"):
            _require(new.get(field) == old.get(field), "changed committed heap state or schema")
        _require(new.get("intrabar_persistence", {}).get("committed", False)
                 == old.get("intrabar_persistence", {}).get("committed", False),
                 "changed committed heap persistence")
        if old.get("intrabar_persistence", {}).get("working", False):
            _require(new.get("intrabar_persistence", {}).get("working", False), "lost working heap persistence")
    for key, row in objects.items():
        if key not in old_objects:
            _require(not row["committed_exists"] and row["committed_revision"] == 0
                     and not row.get("intrabar_persistence", {}).get("committed", False),
                     "introduced committed heap state")
