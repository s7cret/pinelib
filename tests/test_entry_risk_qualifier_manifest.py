"""Delegated qualifier metadata agrees with the already admitted entry-rule scope."""

import json
from importlib.resources import files

import pytest

from pinelib.abi.builder import build_manifest
from pinelib.abi.manifest_v2_builder import _audited_signature


@pytest.mark.parametrize(
    "name,parameter",
    [
        ("strategy.risk.allow_entry_in", "value"),
        ("strategy.risk.max_position_size", "contracts"),
    ],
)
def test_fixed_per_run_risk_inputs_are_declared_simple(name, parameter):
    manifest = build_manifest()
    row = next(r for r in manifest["rows"] if r["name"] == name)
    assert row["disposition"] == "TARGET_DELEGATED"
    assert row["parameters"][0]["name"] == parameter
    assert row["parameters"][0]["qualifier_max"] == "simple"
    assert row["delegation"]["owner"] == "backtest-engine"


def test_checked_in_manifest_reproduces_exactly():
    assert build_manifest() == json.loads(
        files("pinelib.abi").joinpath("target_manifest.json").read_text()
    )


def test_audited_projection_does_not_mutate_frozen_input_or_other_risk_rules():
    original = {
        "name": "strategy.risk.max_position_size",
        "category": "functions",
        "parameters": [
            {
                "name": "contracts",
                "type": "float",
                "required": True,
                "qualifier_max": "const",
            }
        ],
    }
    result = _audited_signature(original)
    assert original["parameters"][0]["qualifier_max"] == "const"
    assert result["parameters"][0]["qualifier_max"] == "simple"
    other = {**original, "name": "strategy.risk.max_drawdown"}
    assert _audited_signature(other) == other


def test_only_two_qualifier_fields_change_against_published_manifest():
    """The delta fixture came from base Git bytes + two literal edits, not build_manifest."""
    import hashlib
    from pathlib import Path

    proof = json.loads(
        (Path(__file__).parent / "fixtures/entry_risk_qualifier_delta.json").read_text()
    )
    manifest = build_manifest()
    assert manifest["content_hash"] == proof["expected_content_hash"]
    names = set()
    for change in proof["row_changes"]:
        before, after = change["before"], change["after"]
        assert before["parameters"][0]["qualifier_max"] == "const"
        before["parameters"][0]["qualifier_max"] = "simple"
        assert before == after
        names.add(after["name"])
        assert (
            next(row for row in manifest["rows"] if row["name"] == after["name"])
            == after
        )
    assert names == {"strategy.risk.max_position_size", "strategy.risk.allow_entry_in"}
    manifest.pop("content_hash")
    manifest["rows"] = [row for row in manifest["rows"] if row["name"] not in names]
    encoded = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == proof["unchanged_remainder_sha256"]
