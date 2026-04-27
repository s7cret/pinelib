from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def check(manifest_path: Path, *, require_head: bool) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_path = ROOT / str(manifest["archive"])
    if not archive_path.is_file():
        raise SystemExit(f"Archive missing: {archive_path}")
    actual_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if manifest.get("archive_sha256") != actual_sha:
        raise SystemExit(
            f"Archive SHA mismatch for {archive_path.name}: manifest={manifest.get('archive_sha256')} actual={actual_sha}"
        )
    commit = manifest.get("git_commit")
    if not isinstance(commit, str) or len(commit) < 7:
        raise SystemExit("Manifest git_commit must be a git commit hash string")
    subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=True)
    if require_head and commit != _head():
        raise SystemExit(f"Manifest git_commit does not match HEAD: manifest={commit} HEAD={_head()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate PineLib release manifest/archive integrity.")
    parser.add_argument("manifest", nargs="?", default=None)
    parser.add_argument("--require-head", action="store_true")
    args = parser.parse_args()
    manifests = [ROOT / args.manifest] if args.manifest else sorted(ROOT.glob("RELEASE_MANIFEST_v*.json"))
    for manifest in manifests:
        check(manifest, require_head=args.require_head)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
