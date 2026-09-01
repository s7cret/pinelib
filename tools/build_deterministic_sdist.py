from __future__ import annotations

import argparse
import gzip
import io
import tarfile
from pathlib import Path

_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
_EXCLUDED_NAMES = {".coverage"}
_ROOT_NAME = "pinelib-5.0.0rc6"


def selected_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(
                f"refusing symlink in source tree: {path.relative_to(root)}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(
            part in _EXCLUDED_PARTS or part.endswith((".egg-info", ".dist-info"))
            for part in relative.parts
        ):
            continue
        if path.suffix in _EXCLUDED_SUFFIXES or path.name in _EXCLUDED_NAMES:
            continue
        result.append(path)
    return result


def build(root: Path, output: Path, *, epoch: int) -> None:
    tar_bytes = io.BytesIO()
    with tarfile.open(
        fileobj=tar_bytes, mode="w", format=tarfile.PAX_FORMAT
    ) as archive:
        for path in selected_files(root):
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            info = tarfile.TarInfo(f"{_ROOT_NAME}/{relative}")
            info.size = len(data)
            info.mtime = epoch
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            archive.addfile(info, io.BytesIO(data))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9
    ) as stream:
        stream.write(tar_bytes.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--epoch", type=int, default=1_700_000_000)
    arguments = parser.parse_args()
    build(
        Path(arguments.root).resolve(),
        Path(arguments.output).resolve(),
        epoch=arguments.epoch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
