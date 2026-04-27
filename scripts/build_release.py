from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pinelib.version import PACKAGE_VERSION, RUNTIME_CONTRACT_VERSION

VERSION_SLUG = PACKAGE_VERSION.replace(".", "_")
MANIFEST_PATH = ROOT / f"RELEASE_MANIFEST_v{VERSION_SLUG}.json"
ARCHIVE_PATH = ROOT / f"pinelib_runtime_v{VERSION_SLUG}.zip"
ZIP_TIMESTAMP = (2024, 1, 1, 0, 0, 0)
INCLUDE_PATHS = [
    ROOT / "README.md",
    *sorted(ROOT.glob("CHANGELOG_v*.md")),
    *sorted(ROOT.glob("RELEASE_NOTES_v*.md")),
    *sorted(ROOT.glob("FINAL_AUDIT_v*.md")),
    ROOT / "pyproject.toml",
]


def _release_files() -> list[Path]:
    files = sorted((ROOT / "pinelib").rglob("*.py"))
    files.extend(sorted((ROOT / "pinelib").rglob("py.typed")))
    files.extend(sorted((ROOT / "tests").rglob("*.py")))
    files.extend(sorted((ROOT / "scripts").glob("*.py")))
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    files.extend(sorted((ROOT / "docs").rglob("*.json")))
    files.extend(path for path in sorted((ROOT / "fixtures").rglob("*")) if path.is_file())
    files.extend(sorted((ROOT / ".github" / "workflows").glob("*.yml")))
    files.extend(sorted((ROOT / ".github" / "workflows").glob("*.yaml")))
    return files


def _zip_write(zip_file: ZipFile, file_path: Path) -> None:
    relative_name = file_path.relative_to(ROOT).as_posix()
    info = ZipInfo(relative_name, date_time=ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zip_file.writestr(info, file_path.read_bytes())


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def build_release() -> None:
    files = [*INCLUDE_PATHS, *_release_files()]
    files = sorted(set(files), key=lambda path: path.relative_to(ROOT).as_posix())
    with ZipFile(ARCHIVE_PATH, "w") as archive:
        for file_path in files:
            _zip_write(archive, file_path)

    sha256 = hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest()
    manifest = {
        "package": "pinelib",
        "version": PACKAGE_VERSION,
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "archive": ARCHIVE_PATH.name,
        "archive_sha256": sha256,
        "git_commit": _git_commit(),
        "files": [path.relative_to(ROOT).as_posix() for path in files],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build_release()
