from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pinelib.distribution import manifest as distribution_manifest
from pinelib.version import PACKAGE_VERSION, RUNTIME_CONTRACT_VERSION

CANONICAL_DOCS = {
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/COMPATIBILITY.md",
    "docs/DEVELOPMENT.md",
    "docs/RELEASE_4_0.md",
    "docs/SECURITY.md",
}


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    package: str
    version: str
    contract_version: str
    ok: bool
    errors: list[str]


def _pyproject_version(root: Path) -> str | None:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else None


def validate(root: str | Path = ".") -> ReleaseReport:
    base = Path(root).resolve()
    errors: list[str] = []
    if _pyproject_version(base) != PACKAGE_VERSION:
        errors.append("pyproject.toml version does not match pinelib.version.PACKAGE_VERSION")
    if PACKAGE_VERSION != "4.0.0":
        errors.append("PineLib release package should be version 4.0.0")
    if not (base / "README.md").read_text(encoding="utf-8").count("4.0.0"):
        errors.append("README.md does not mention release 4.0.0")
    if not (base / "CHANGELOG.md").is_file():
        errors.append("CHANGELOG.md is missing")
    else:
        changelog = (base / "CHANGELOG.md").read_text(encoding="utf-8")
        if "4.0.0" not in changelog:
            errors.append("CHANGELOG.md does not contain 4.0.0")
    docs = {path.relative_to(base).as_posix() for path in (base / "docs").glob("*.md")}
    missing_docs = sorted(CANONICAL_DOCS - docs)
    extra_docs = sorted(docs - CANONICAL_DOCS)
    if missing_docs:
        errors.append(f"missing canonical docs: {missing_docs}")
    if extra_docs:
        errors.append(f"unexpected docs: {extra_docs}")
    dist = distribution_manifest(base)
    if not dist.archive_hygiene_ok:
        errors.append(f"distribution hygiene failed: {dist.forbidden_files[:10]}")
    return ReleaseReport(
        package="pinelib",
        version=PACKAGE_VERSION,
        contract_version=RUNTIME_CONTRACT_VERSION,
        ok=not errors,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate PineLib release readiness")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    report = validate(args.root)
    payload = json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
    if args.json:
        Path(args.json).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
