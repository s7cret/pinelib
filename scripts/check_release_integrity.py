from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent


def check(archive: Path) -> None:
    if not archive.is_file():
        raise SystemExit(f"Archive missing: {archive}")
    with ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise SystemExit(f"Corrupt zip entry: {bad}")
        names = set(zf.namelist())
        required_suffixes = {
            "README.md",
            "pyproject.toml",
            "pinelib/__init__.py",
            "tests/conftest.py",
        }
        for suffix in required_suffixes:
            if not any(name.endswith(suffix) for name in names):
                raise SystemExit(f"Archive is missing {suffix}")
    print(hashlib.sha256(archive.read_bytes()).hexdigest())


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate PineLib release archive integrity")
    parser.add_argument("archive", nargs="?", default="pinelib-4.0.0.zip")
    args = parser.parse_args()
    check(ROOT / args.archive)


if __name__ == "__main__":
    main()
