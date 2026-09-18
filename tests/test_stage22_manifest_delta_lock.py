from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from tests.stage2_audit_repair_helpers import restore_audit_repair

from tests.stage21_post_audit_helpers import _restore_stage22_surface, _restore_stage22_target


def _content_hash(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def test_stage22_manifest_delta_is_explicit_and_denominator_preserving():
    root = files("pinelib.abi")
    lock = json.loads(root.joinpath("stage22_manifest_delta_lock.json").read_text())
    target = restore_audit_repair(json.loads(root.joinpath("target_manifest.json").read_text()), "target_manifest.json")
    surface = restore_audit_repair(json.loads(root.joinpath("official_pine_v6_surface.json").read_text()), "official_pine_v6_surface.json")

    assert lock["schema_id"] == "pinelib.stage22_manifest_delta.v1"
    assert _content_hash(lock) == lock["content_hash"]
    assert lock["policy"] == {
        "denominator_changed": False,
        "historical_stage21_evidence_rewritten": False,
        "rows_added": 0,
        "rows_removed": 0,
    }
    assert target["content_hash"] == lock["target_manifest"]["after_content_hash"]
    assert surface["content_hash"] == lock["official_surface"]["after_content_hash"]
    assert len(target["rows"]) == len(surface["rows"]) == 1108


def test_stage22_bool_int_bindings_are_direct_and_historical_stage21_is_reconstructible():
    root = files("pinelib.abi")
    lock = json.loads(root.joinpath("stage22_manifest_delta_lock.json").read_text())
    target = restore_audit_repair(json.loads(root.joinpath("target_manifest.json").read_text()), "target_manifest.json")
    surface = restore_audit_repair(json.loads(root.joinpath("official_pine_v6_surface.json").read_text()), "official_pine_v6_surface.json")

    rows = {(r["category"], r["name"], r["symbol_id"]): r for r in target["rows"]}
    for name in ("bool", "int"):
        row = rows[("functions", name, f"pine:function:{name}")]
        assert row["disposition"] == "TARGET_DIRECT"
        assert row["diagnostic"] is None
        assert any(p["binding"] == "SOURCE_PARAMETER" for p in row["parameter_bindings"])

    bool_surface = next(
        r for r in surface["rows"]
        if r["category"] == "functions" and r["name"] == "bool" and r["symbol_id"] == "pine:function:bool"
    )
    assert [p["name"] for p in bool_surface["parameters"]] == ["value"]
    assert _restore_stage22_target(target)["content_hash"] == lock["target_manifest"]["before_content_hash"]
    assert _restore_stage22_surface(surface)["content_hash"] == lock["official_surface"]["before_content_hash"]
