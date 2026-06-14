from __future__ import annotations

import argparse

from pinelib.version import PACKAGE_VERSION, RUNTIME_CONTRACT_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PineLib runtime utilities")
    parser.add_argument("--version", action="store_true", help="Print package version")
    args = parser.parse_args(argv)
    if args.version:
        print(PACKAGE_VERSION)
    else:
        print(f"PineLib {PACKAGE_VERSION} runtime_contract_v{RUNTIME_CONTRACT_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
