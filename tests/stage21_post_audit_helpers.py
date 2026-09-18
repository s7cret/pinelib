"""Restore the frozen pre-audit Stage 2.1 manifest endpoint for historical hash tests.

The repair delta is itself frozen in pinelib.abi/stage21_post_audit_manifest_delta_lock.json.
This keeps older evidence immutable while allowing the reviewed ta.rma contract repair.
"""
from __future__ import annotations

from copy import deepcopy
from tests.stage2_audit_repair_helpers import restore_audit_repair
import json
from importlib.resources import files


def _lock() -> dict:
    return json.loads(
        files("pinelib.abi").joinpath("stage21_post_audit_manifest_delta_lock.json").read_text()
    )




def _stage22_lock() -> dict:
    return json.loads(
        files("pinelib.abi").joinpath("stage22_manifest_delta_lock.json").read_text()
    )


def _restore_stage22_target(manifest: dict) -> dict:
    restored = restore_audit_repair(manifest, "target_manifest.json")
    lock = _stage22_lock()["target_manifest"]
    if restored.get("content_hash") != lock["after_content_hash"]:
        return restored
    for name, delta in lock["symbols"].items():
        matches = [i for i, row in enumerate(restored["rows"]) if row.get("category") == "functions" and row.get("name") == name and row.get("symbol_id") == f"pine:function:{name}"]
        assert len(matches) == 1
        assert restored["rows"][matches[0]] == delta["after"]
        restored["rows"][matches[0]] = deepcopy(delta["before"])
    for key, value in lock["before_top_level"].items():
        restored[key] = deepcopy(value)
    restored["content_hash"] = lock["before_content_hash"]
    return restored


def _restore_stage22_surface(surface: dict) -> dict:
    restored = restore_audit_repair(surface, "official_pine_v6_surface.json")
    lock = _stage22_lock()["official_surface"]
    if restored.get("content_hash") != lock["after_content_hash"]:
        return restored
    delta = lock["symbols"]["bool"]
    matches = [i for i, row in enumerate(restored["rows"]) if row.get("category") == "functions" and row.get("name") == "bool" and row.get("symbol_id") == "pine:function:bool"]
    assert len(matches) == 1
    assert restored["rows"][matches[0]] == delta["after"]
    restored["rows"][matches[0]] = deepcopy(delta["before"])
    for key, value in lock["before_top_level"].items():
        restored[key] = deepcopy(value)
    restored["content_hash"] = lock["before_content_hash"]
    return restored

def restore_pre_audit_target(manifest: dict) -> dict:
    restored = _restore_stage22_target(manifest)
    lock = _lock()["target_manifest"]
    assert restored["content_hash"] == lock["after_content_hash"]
    rows = restored["rows"]
    current = lock["after_ta_rma"]
    previous = lock["before_ta_rma"]
    matches = [index for index, row in enumerate(rows) if row == current]
    assert len(matches) == 1
    rows[matches[0]] = deepcopy(previous)
    for key, value in lock["before_top_level"].items():
        restored[key] = deepcopy(value)
    restored["content_hash"] = lock["before_content_hash"]
    return restored


def restore_pre_audit_surface(surface: dict) -> dict:
    restored = _restore_stage22_surface(surface)
    lock = _lock()["official_surface"]
    assert restored["content_hash"] == lock["after_content_hash"]
    rows = restored["rows"]
    current = lock["after_ta_rma"]
    previous = lock["before_ta_rma"]
    matches = [index for index, row in enumerate(rows) if row == current]
    assert len(matches) == 1
    rows[matches[0]] = deepcopy(previous)
    for key, value in lock["before_top_level"].items():
        restored[key] = deepcopy(value)
    restored["content_hash"] = lock["before_content_hash"]
    return restored
