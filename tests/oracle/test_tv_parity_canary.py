from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tv_parity_canary_emits_sanitized_machine_readable_evidence(tmp_path: Path) -> None:
    output = tmp_path / "tv-parity-canary.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_tv_parity_canary.py"),
            "--json",
            str(output),
            "--validated-at",
            "2026-07-12T00:00:00Z",
            "--git-sha",
            "a" * 40,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text())
    assert payload["schema"] == "pinelib.tv-parity-canary.v1"
    assert payload["status"] == "pass_with_platform_blocked"
    assert payload["validated_at"] == "2026-07-12T00:00:00Z"
    assert payload["repository_sha"] == "a" * 40
    assert payload["contract_version"] == "1.4"
    assert len(payload["fixture_manifest_sha256"]) == 64
    assert payload["counts"]["assertions_evaluated"] >= 30
    assert payload["counts"]["oracle_verified"] > 0
    assert payload["counts"]["platform_blocked"] == 1
    assert payload["counts"]["pending_external_oracle"] == 0
    serialized = json.dumps(payload).lower()
    for forbidden in ("trades", "equity", "profit", "pnl", "indicator_values"):
        assert forbidden not in serialized
