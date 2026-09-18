"""Stage 2.10: runtime ABI file and package version stay bound to the publication lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import pinelib

LOCK = Path(__file__).resolve().parents[1] / "pinelib/abi/stage2_10_language_publication.json"
MANIFEST = Path(__file__).resolve().parents[1] / "pinelib/abi/target_manifest.json"


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_stage210_runtime_abi_matches_publication():
    lock = json.loads(LOCK.read_text())
    assert lock["packages"]["pinelib"] == pinelib.__version__
    assert lock["runtime_target_file_hash"] == _file_sha256(MANIFEST)
    assert lock["full_stage2_accepted"] is False
    assert lock.get("residuals")


def test_stage210_unpublished_runtime_abi_change_stops_publication():
    pytest.importorskip("pine2ast")
    from pine2ast.hardening.language_publication import (
        LanguagePublicationError,
        observe_language_publication,
        verify_language_publication,
    )

    observed = observe_language_publication(
        pinelib_version=pinelib.__version__,
        runtime_target_file_hash="sha256:" + "0" * 64,
    )
    with pytest.raises(LanguagePublicationError, match="runtime_target_file_hash"):
        verify_language_publication(observation=observed)
