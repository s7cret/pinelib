from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

from pinelib.abi.builder import build_manifest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "build_deterministic_sdist.py"
SCANNER = ROOT / "tools" / "forbidden_scan.py"
EPOCH = 1_700_000_000


def _run_tool(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_deterministic_sdist_is_byte_identical_and_normalized(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    for output in (first, second):
        result = _run_tool(
            str(BUILDER),
            "--root",
            str(ROOT),
            "--output",
            str(output),
            "--epoch",
            str(EPOCH),
        )
        assert result.returncode == 0, result.stderr

    assert (
        hashlib.sha256(first.read_bytes()).digest()
        == hashlib.sha256(second.read_bytes()).digest()
    )
    with first.open("rb") as raw:
        stream = gzip.GzipFile(fileobj=raw)
        stream.read(1)
        assert stream.mtime == EPOCH
    with tarfile.open(first, "r:gz") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(
            member.name for member in members
        )
        assert all(member.isfile() for member in members)
        assert all(member.mtime == EPOCH for member in members)
        assert all(member.uid == member.gid == 0 for member in members)
        assert all(member.uname == member.gname == "root" for member in members)
        assert all(member.name.startswith("pinelib-5.0.0rc6/") for member in members)
        assert not any(
            part in {"build", "dist", "__pycache__"}
            or part.endswith((".egg-info", ".dist-info"))
            for member in members
            for part in Path(member.name).parts
        )


def test_deterministic_sdist_rejects_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "alias.py").symlink_to("target.py")
    output = tmp_path / "artifact.tar.gz"

    result = _run_tool(
        str(BUILDER),
        "--root",
        str(source),
        "--output",
        str(output),
        "--epoch",
        str(EPOCH),
    )

    assert result.returncode != 0
    assert "refusing symlink" in result.stderr
    assert not output.exists()


def test_deterministic_sdist_normalizes_file_modes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    plain = source / "plain.py"
    executable = source / "tool.py"
    plain.write_text("VALUE = 1\n", encoding="utf-8")
    executable.write_text("VALUE = 2\n", encoding="utf-8")
    plain.chmod(0o600)
    executable.chmod(0o711)
    output = tmp_path / "artifact.tar.gz"

    result = _run_tool(
        str(BUILDER),
        "--root",
        str(source),
        "--output",
        str(output),
        "--epoch",
        str(EPOCH),
    )

    assert result.returncode == 0, result.stderr
    with tarfile.open(output, "r:gz") as archive:
        modes = {member.name: member.mode for member in archive.getmembers()}
    assert modes == {
        "pinelib-5.0.0rc6/plain.py": 0o644,
        "pinelib-5.0.0rc6/tool.py": 0o755,
    }


def test_forbidden_scan_records_exact_package_root_command() -> None:
    result = _run_tool(str(SCANNER), "--root", "pinelib")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_id"] == "pinelib.stage4.forbidden_scan.v1"
    assert report["pass"] is True
    assert report["command"] == ["tools/forbidden_scan.py", "--root", "pinelib"]
    assert report["scan_root"] == "pinelib"


def test_every_delegated_target_has_exact_canonical_overload_identity() -> None:
    rows = build_manifest()["rows"]
    assert isinstance(rows, list)
    delegated = [
        row
        for row in rows
        if isinstance(row, dict) and row["disposition"] == "TARGET_DELEGATED"
    ]

    assert delegated
    for row in delegated:
        canonical = f"{row['symbol_id']}#canonical"
        assert row["overload_id"] == canonical
        assert row["producer_overload_ids"] == [canonical]
