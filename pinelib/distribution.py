from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pinelib.version import PACKAGE_VERSION, RUNTIME_CONTRACT_VERSION

ZIP_TIMESTAMP = (2024, 1, 1, 0, 0, 0)
EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    "build",
    "dist",
    "htmlcov",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".coverage", ".log"}
EXCLUDED_NAMES = {".coverage"}
INCLUDED_TOP_LEVEL = {
    ".github",
    "docs",
    "fixtures",
    "pinelib",
    "scripts",
    "tests",
    "CHANGELOG.md",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "docker-compose.yml",
    "pyproject.toml",
}


@dataclass(frozen=True, slots=True)
class DistributionManifest:
    package: str
    version: str
    contract_version: str
    root: str
    file_count: int
    archive_hygiene_ok: bool
    forbidden_files: list[str]


def _is_included(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if not rel.parts:
        return False
    if rel.parts[0] not in INCLUDED_TOP_LEVEL:
        return False
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.name in EXCLUDED_NAMES:
        return False
    if any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    if path.suffix == ".zip":
        return False
    if path.suffix == ".egg-info" or any(part.endswith(".egg-info") for part in rel.parts):
        return False
    return path.is_file()


def source_files(root: str | Path) -> list[Path]:
    base = Path(root).resolve()
    return sorted(path for path in base.rglob("*") if _is_included(path, base))


def manifest(root: str | Path) -> DistributionManifest:
    base = Path(root).resolve()
    files = source_files(base)
    forbidden = [
        path.relative_to(base).as_posix()
        for path in files
        if (
            any(part in EXCLUDED_PARTS for part in path.relative_to(base).parts)
            or path.name in EXCLUDED_NAMES
            or path.suffix in {".pyc", ".pyo"}
            or path.suffix == ".zip"
            or path.suffix == ".egg-info"
            or any(part.endswith(".egg-info") for part in path.relative_to(base).parts)
        )
    ]
    return DistributionManifest(
        package="pinelib",
        version=PACKAGE_VERSION,
        contract_version=RUNTIME_CONTRACT_VERSION,
        root=str(base),
        file_count=len(files),
        archive_hygiene_ok=not forbidden,
        forbidden_files=sorted(forbidden),
    )


def build_zip(root: str | Path, output: str | Path) -> str:
    base = Path(root).resolve()
    archive_path = Path(output).resolve()
    root_prefix = f"pinelib-{PACKAGE_VERSION}"
    with ZipFile(archive_path, "w") as archive:
        for file_path in source_files(base):
            rel = file_path.relative_to(base).as_posix()
            info = ZipInfo(f"{root_prefix}/{rel}", date_time=ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, file_path.read_bytes())
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic PineLib source archives")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest_parser = sub.add_parser("manifest")
    manifest_parser.add_argument("--root", default=".")
    manifest_parser.add_argument("--json", action="store_true")
    zip_parser = sub.add_parser("build-zip")
    zip_parser.add_argument("--root", default=".")
    zip_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "manifest":
        payload = manifest(args.root)
        if args.json:
            print(json.dumps(asdict(payload), indent=2, sort_keys=True))
        else:
            for key, value in asdict(payload).items():
                print(f"{key}: {value}")
        return 0 if payload.archive_hygiene_ok else 1
    digest = build_zip(args.root, args.output)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
