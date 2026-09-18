"""Freeze both the original Stage 2.1 delta and the reviewed post-audit ta.rma repair."""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from tests.stage21_post_audit_helpers import (
    _restore_stage22_surface,
    _restore_stage22_target,
    restore_pre_audit_surface,
    restore_pre_audit_target,
)


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(value):
    return hashlib.sha256(_canon(value)).hexdigest()


def _target_key(row):
    return "|".join(str(row.get(key) or "") for key in (
        "category", "name", "symbol_id", "overload_id", "call_form"
    ))


def _surface_key(row):
    return "|".join(str(row.get(key) or "") for key in ("category", "name", "symbol_id"))


def _assert_historical_current(rows, lock, key):
    current = {key(row): row for row in rows}
    affected = set(lock["added"]) | set(lock["changed"])
    unaffected = sorted(set(current) - affected)
    assert len(current) == lock["after_count"]
    assert _hash(sorted(current)) == lock["current_all_keys_hash"]
    assert _hash([current[name] for name in unaffected]) == lock["after_unaffected_hash"]
    assert _hash([current[name] for name in sorted(affected)]) == lock["current_affected_hash"]


def _assert_post_audit_current(rows, repair, key):
    current = {tuple(key(row)): row for row in rows}
    changed = {tuple(value) for value in repair["changed_row_keys"]}
    assert set(current) >= changed
    unaffected = [current[name] for name in sorted(set(current) - changed, key=str)]
    assert _hash(unaffected) == repair["unaffected_rows_sha256"]


def _target_tuple(row):
    return (
        row.get("category"), row.get("name"), row.get("symbol_id"),
        row.get("overload_id"), row.get("call_form"),
    )


def _surface_tuple(row):
    return (row.get("category"), row.get("name"), row.get("symbol_id"))


def test_original_stage21_target_delta_remains_reproducible_before_post_audit_repair():
    root = files("pinelib.abi")
    historical = json.loads(root.joinpath("stage21_manifest_delta_lock.json").read_text())
    current = json.loads(root.joinpath("target_manifest.json").read_text())
    baseline = restore_pre_audit_target(current)
    repair = json.loads(root.joinpath("stage21_post_audit_manifest_delta_lock.json").read_text())

    assert historical["schema_id"] == "pinelib.stage21_manifest_delta.v1"
    assert baseline["content_hash"] == historical["current_target_content_hash"]
    assert repair["target_manifest"]["before_content_hash"] == baseline["content_hash"]
    assert historical["target_rows"]["before_count"] == historical["target_rows"]["after_count"] == 1108
    assert not historical["target_unrelated_row_changes"]
    assert historical["target_rows"]["before_unaffected_hash"] == historical["target_rows"]["after_unaffected_hash"]
    assert historical["policy"]["rows_removed_from_denominator"] == 0
    _assert_historical_current(baseline["rows"], historical["target_rows"], _target_key)


def test_post_audit_target_delta_is_exactly_ta_rma_without_denominator_drift():
    root = files("pinelib.abi")
    repair = json.loads(root.joinpath("stage21_post_audit_manifest_delta_lock.json").read_text())
    manifest = _restore_stage22_target(json.loads(root.joinpath("target_manifest.json").read_text()))
    target = repair["target_manifest"]

    assert repair["schema_id"] == "pinelib.stage21_post_audit_manifest_delta.v1"
    assert manifest["content_hash"] == target["after_content_hash"]
    assert target["before_count"] == target["after_count"] == 1108
    assert repair["policy"]["added_rows"] == repair["policy"]["removed_rows"] == 0
    assert repair["policy"]["unrelated_target_row_changes"] == 0
    assert target["changed_row_keys"] == [[
        "functions", "ta.rma", "pine:function:ta.rma", "pine:function:ta.rma#v1", "namespace_function"
    ]]
    assert target["before_ta_rma"]["parameters"] == []
    assert [p["name"] for p in target["after_ta_rma"]["parameters"]] == ["source", "length"]
    bindings = {p["abi_parameter"]: p for p in target["after_ta_rma"]["parameter_bindings"]}
    assert bindings["source"]["binding"] == "SOURCE_PARAMETER"
    assert bindings["length"]["binding"] == "SOURCE_PARAMETER"
    _assert_post_audit_current(manifest["rows"], target, _target_tuple)


def test_original_stage21_surface_delta_remains_reproducible_before_post_audit_repair():
    root = files("pinelib.abi")
    historical = json.loads(root.joinpath("stage21_manifest_delta_lock.json").read_text())
    current = json.loads(root.joinpath("official_pine_v6_surface.json").read_text())
    baseline = restore_pre_audit_surface(current)
    repair = json.loads(root.joinpath("stage21_post_audit_manifest_delta_lock.json").read_text())

    assert baseline["content_hash"] == historical["current_surface_content_hash"]
    assert repair["official_surface"]["before_content_hash"] == baseline["content_hash"]
    assert historical["surface_rows"]["before_count"] == historical["surface_rows"]["after_count"] == 1108
    assert historical["surface_rows"]["before_unaffected_hash"] == historical["surface_rows"]["after_unaffected_hash"]
    _assert_historical_current(baseline["rows"], historical["surface_rows"], _surface_key)


def test_post_audit_surface_delta_is_exactly_ta_rma_and_oracles_are_untouched():
    root = files("pinelib.abi")
    repair = json.loads(root.joinpath("stage21_post_audit_manifest_delta_lock.json").read_text())
    surface = _restore_stage22_surface(json.loads(root.joinpath("official_pine_v6_surface.json").read_text()))
    current = repair["official_surface"]

    assert surface["content_hash"] == current["after_content_hash"]
    assert current["before_count"] == current["after_count"] == 1108
    assert repair["policy"]["unrelated_surface_row_changes"] == 0
    assert repair["policy"]["manual_numerical_expectations_changed"] is False
    assert current["changed_row_keys"] == [["functions", "ta.rma", "pine:function:ta.rma"]]
    assert current["before_ta_rma"]["parameters"] == []
    assert [p["name"] for p in current["after_ta_rma"]["parameters"]] == ["source", "length"]
    _assert_post_audit_current(surface["rows"], current, _surface_tuple)
