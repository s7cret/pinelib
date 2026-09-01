from __future__ import annotations

import argparse
from pathlib import Path

from pinelib.abi.builder import check_manifest, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m pinelib.abi")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--check", action="store_true")
    build.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("target_manifest.json"),
    )
    arguments = parser.parse_args()
    if arguments.command == "build":
        if arguments.check:
            check_manifest(arguments.output)
        else:
            write_manifest(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
