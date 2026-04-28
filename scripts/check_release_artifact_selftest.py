from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def check(archive_path: Path) -> None:
    if not archive_path.is_file():
        raise SystemExit(f"Archive missing: {archive_path}")
    with tempfile.TemporaryDirectory(prefix="pinelib-artifact-") as tmp:
        extract_root = Path(tmp) / "extract"
        with ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            required = {
                "scripts/run_tv_golden_suite.py",
                "fixtures/tradingview/cases.json",
            }
            missing = sorted(required - names)
            if missing:
                raise SystemExit(f"Archive is missing required oracle evidence paths: {missing}")
            archive.extractall(extract_root)
        cases_path = extract_root / "fixtures" / "tradingview" / "cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        for case in cases.get("cases", []):
            for key in ("source", "oracle", "expected"):
                value = case.get(key)
                if isinstance(value, str) and value:
                    candidate = extract_root / value
                    if not candidate.exists():
                        raise SystemExit(
                            f"Archive missing fixture reference for case {case.get('id')}: {value}"
                        )
        _run([sys.executable, "scripts/run_tv_golden_suite.py"], cwd=extract_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and self-test a PineLib release archive.")
    parser.add_argument("archive", nargs="?", default="pinelib_runtime_v1_0_1.zip")
    args = parser.parse_args()
    check(ROOT / args.archive)


if __name__ == "__main__":
    main()
