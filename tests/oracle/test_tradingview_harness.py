from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_tradingview_oracle_manifest_counts_verified_and_pending_cases() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "fixtures" / "tradingview" / "cases.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    statuses = {case["status"] for case in cases}
    assert statuses <= {"oracle_verified", "golden_synthetic", "pending_external_oracle"}

    for case in cases:
        if case["status"] != "oracle_verified":
            continue
        case_dir = manifest_path.parent / case["id"]
        for required_file in case["required_files"]:
            assert (case_dir / required_file).is_file()

    result = subprocess.run(
        [sys.executable, "scripts/run_tv_golden_suite.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["oracle_verified"] == sum(case["status"] == "oracle_verified" for case in cases)
    assert summary["pending_external_oracle"] == sum(case["status"] == "pending_external_oracle" for case in cases)
