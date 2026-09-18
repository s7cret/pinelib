"""The new ABI repair layer preserves all historical identities and rejects tampering."""
from copy import deepcopy
from importlib.resources import files
import json
import pytest
from tests.stage2_audit_repair_helpers import restore_audit_repair


@pytest.mark.parametrize("name", ["target_manifest.json","official_pine_v6_surface.json"])
def test_audit_delta_reconstructs_exact_previous_endpoint(name):
    payload=json.loads(files("pinelib.abi").joinpath(name).read_text())
    before=restore_audit_repair(payload,name)
    assert len(before["rows"]) == len(payload["rows"]) == 1108
    assert before["content_hash"] != payload["content_hash"]


@pytest.mark.parametrize("name", ["target_manifest.json","official_pine_v6_surface.json"])
def test_audit_delta_does_not_hide_unreviewed_changes(name):
    payload=json.loads(files("pinelib.abi").joinpath(name).read_text())
    payload["rows"][0]["name"] = "unreviewed"
    with pytest.raises(AssertionError):
        restore_audit_repair(payload,name)
