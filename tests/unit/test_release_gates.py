from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from pinelib import distribution, quality, release
from pinelib.__main__ import main as pinelib_main
from pinelib.distribution import main as distribution_main
from pinelib.quality import main as quality_main
from pinelib.release import main as release_main
from pinelib.version import PACKAGE_VERSION, RUNTIME_CONTRACT_VERSION


def _minimal_release_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pinelib").mkdir()
    (root / "pinelib" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_smoke.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / "fixtures").mkdir()
    (root / "fixtures" / "sample.txt").write_text("fixture\n", encoding="utf-8")
    (root / ".github").mkdir()
    (root / ".github" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (root / "docs").mkdir()
    for doc in release.CANONICAL_DOCS:
        path = root / doc
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\nPineLib {PACKAGE_VERSION}.\n", encoding="utf-8")
    (root / "README.md").write_text(f"# PineLib {PACKAGE_VERSION}\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(f"## {PACKAGE_VERSION}\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pinelib"\nversion = "4.0.0"\n',
        encoding="utf-8",
    )
    return root


def test_module_entrypoint_prints_version_and_contract(capsys: pytest.CaptureFixture[str]) -> None:
    assert pinelib_main(["--version"]) == 0
    assert PACKAGE_VERSION in capsys.readouterr().out
    assert pinelib_main([]) == 0
    out = capsys.readouterr().out
    assert PACKAGE_VERSION in out
    assert RUNTIME_CONTRACT_VERSION in out


def test_quality_duplicate_and_architecture_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "small.py").write_text("x = 1\n", encoding="utf-8")
    duplicate_report = quality.duplicates(root)
    assert duplicate_report.duplicate_group_count == 0
    assert quality_main(["duplicates", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["duplicate_group_count"] == 0

    (root / "large.py").write_text("\n".join("x = 1" for _ in range(5)) + "\n", encoding="utf-8")
    architecture_report = quality.architecture(root, max_lines=3)
    assert architecture_report.oversized_count == 1
    assert quality_main(["architecture", str(root), "--max-lines", "3"]) == 1
    assert "oversized_count" in capsys.readouterr().out


def test_distribution_manifest_and_build_zip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _minimal_release_root(tmp_path)
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "ignored.pyc").write_bytes(b"cache")
    report = distribution.manifest(root)
    assert report.archive_hygiene_ok
    assert report.file_count > 0
    assert not report.forbidden_files

    out = tmp_path / "pinelib.zip"
    digest = distribution.build_zip(root, out)
    assert len(digest) == 64
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
    assert f"pinelib-{PACKAGE_VERSION}/README.md" in names
    assert all("__pycache__" not in name for name in names)

    assert distribution_main(["manifest", "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["archive_hygiene_ok"] is True
    out2 = tmp_path / "pinelib2.zip"
    assert distribution_main(["build-zip", "--root", str(root), "--output", str(out2)]) == 0
    assert len(capsys.readouterr().out.strip()) == 64


def test_release_validate_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _minimal_release_root(tmp_path)
    report = release.validate(root)
    assert report.ok
    assert report.version == PACKAGE_VERSION
    assert release_main(["--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    output = tmp_path / "release.json"
    assert release_main(["--root", str(root), "--json", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True


def test_release_validate_reports_missing_docs(tmp_path: Path) -> None:
    root = _minimal_release_root(tmp_path)
    (root / "docs" / "SECURITY.md").unlink()
    report = release.validate(root)
    assert not report.ok
    assert any("missing canonical docs" in error for error in report.errors)
