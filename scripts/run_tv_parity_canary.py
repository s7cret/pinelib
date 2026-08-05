#!/usr/bin/env python3
"""Run the TradingView golden corpus and emit sanitized canary evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_tv_golden_suite as golden

SCHEMA = "pinelib.tv-parity-canary.v1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_report(*, validated_at: str | None = None, git_sha: str | None = None) -> dict[str, Any]:
    manifest = golden.load_cases()
    counts = golden.validate_manifest(manifest, fixtures_root=golden.CASES_PATH.parent)
    fixtures = manifest["fixtures"]
    if not isinstance(fixtures, dict):
        raise ValueError("validated fixture manifest lost its fixtures mapping")
    sources = [
        str(fixture.get("oracle_source", ""))
        for fixture in fixtures.values()
        if isinstance(fixture, dict)
    ]
    capture_dates = sorted(
        {
            match.group(0)
            for source in sources
            for match in re.finditer(r"20\d{2}-\d{2}-\d{2}", source)
        }
    )
    repository_sha = git_sha or os.environ.get("GITHUB_SHA") or "unknown"
    status = "pass_with_platform_blocked" if counts["platform_blocked"] else "pass"
    return {
        "schema": SCHEMA,
        "status": status,
        "validated_at": validated_at or _utc_now(),
        "repository_sha": repository_sha,
        "contract_version": manifest["contract_version"],
        "fixture_manifest_sha256": hashlib.sha256(golden.CASES_PATH.read_bytes()).hexdigest(),
        "oracle_capture_dates": capture_dates,
        "counts": counts,
        "limitations": [
            (
                "Explicit realtime tick-stream oracle remains platform-blocked; "
                "no ticks are fabricated."
            ),
            (
                "This report contains aggregate validation evidence only; "
                "raw oracle rows are not embedded."
            ),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, dest="json_path")
    parser.add_argument("--validated-at", default=None)
    parser.add_argument("--git-sha", default=None)
    args = parser.parse_args(argv)
    report = build_report(validated_at=args.validated_at, git_sha=args.git_sha)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    Path(args.json_path).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
