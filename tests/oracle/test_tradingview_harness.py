from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_tradingview_oracle_manifest_is_harness_only_until_exports_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "fixtures" / "tradingview" / "cases.json").read_text(encoding="utf-8"))
    statuses = {case["status"] for case in manifest["cases"]}
    assert statuses == {"pending_external_oracle"}

    result = subprocess.run(
        [sys.executable, "scripts/run_tv_golden_suite.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["oracle_verified"] == 0
    assert summary["pending_external_oracle"] == len(manifest["cases"])
