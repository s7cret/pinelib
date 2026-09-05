"""Publish reviewed Git objects, never unverified patch output or a force push.

Run only in a repository-scoped CI job. The submission is data: exact source
commits, line edits and an allowlisted deterministic ABI generation recipe.
"""
from __future__ import annotations
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


def run(*args: str, **kwargs):
    return subprocess.check_output(args, **kwargs)


def git(*args: str, **kwargs):
    return run("git", *args, **kwargs)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{40}", value) is not None


def check_remote(submission: dict) -> None:
    require(submission["target"] == "release/5.0.0rc6", "Only the RC6 candidate is writable")
    output = git("ls-remote", "origin", "refs/heads/" + submission["target"], text=True).split()
    require((output[0] if output else None) == submission["expected_target"], "Target moved; nothing overwritten")


def reconstruct(source: Path, evidence: Path) -> None:
    submission = json.loads(source.read_text())
    require(digest(submission["base"]) and digest(submission["head"]), "Invalid candidate identity")
    require(submission["expected_target"] is None or digest(submission["expected_target"]), "Invalid expected target")
    check_remote(submission)
    parts = submission["parts"]
    require(isinstance(parts, list) and 0 < len(parts) <= 256, "Invalid submission parts")
    chunks = []
    for part in parts:
        require(re.fullmatch(r"\.github/maintenance/parts/[0-9]+\.txt", part["path"]) is not None, "Invalid part path")
        raw = Path(part["path"]).read_bytes()
        require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == part["sha256"], "Part checksum mismatch: " + part["path"])
        chunks.append(raw.strip())
    packed = base64.b64decode(b"".join(chunks), validate=True)
    require(len(packed) <= 4000000 and hashlib.sha256(packed).hexdigest() == submission["sha256"], "Submission checksum mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        decoded = stream.read(64000001)
    require(len(decoded) <= 64000000, "Decoded submission too large")
    series = json.loads(decoded)
    require(series["schema"] == "openpine.reviewed-series.v2" and series["repository"] == os.environ["GITHUB_REPOSITORY"], "Wrong source repository or schema")
    require(series["base"] == submission["base"] and series["head"] == submission["head"], "Wrong source commit identities")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "submission.json").write_text(json.dumps(submission, indent=2))
    (evidence / "source-series.json").write_bytes(decoded)
    allowed = {"openpine-contracts", "pine2ast", "ast2python", "pinelib", "backtest_engine", "marketdata-provider", "optimizer"}
    for name, sha in submission.get("dependencies", {}).items():
        require(name in allowed and digest(sha), "Invalid dependency identity")
        checkout = evidence.parent / ("dependency-" + name)
        run("git", "clone", "https://github.com/s7cret/" + name + ".git", str(checkout))
        run("git", "-C", str(checkout), "checkout", "--detach", sha)
        run(sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation", str(checkout))
    git("checkout", "--detach", series["base"])
    root = Path.cwd().resolve()
    for commit in series["commits"]:
        require(git("rev-parse", "HEAD", text=True).strip() == commit["parent"], "Non-contiguous reviewed series")
        recipes = []
        for item in commit["files"]:
            path = item["path"]
            parts = PurePosixPath(path).parts
            require(bool(parts) and ".." not in parts and not path.startswith("/") and parts[0] not in {".git", ".github"}, "Unsafe code path")
            destination = root / path
            require(destination.resolve().is_relative_to(root) and not destination.is_symlink(), "Code path escapes source")
            existing = git("ls-tree", "HEAD", "--", path, text=True).split()
            base = existing[2] if existing else None
            require(base == item["base"], "Base blob mismatch: " + path)
            if item["mode"] == "000000":
                git("rm", "--", path)
                continue
            require(item["mode"] in {"100644", "100755"}, "Unsupported code mode")
            if item.get("regenerate"):
                require(series["repository"] == "s7cret/pinelib" and path == "pinelib/abi/target_manifest.json" and item["regenerate"] == "pinelib-manifest", "Unknown generation recipe")
                recipes.append(item)
                continue
            lines = [] if base is None else git("cat-file", "blob", base).decode().splitlines(keepends=True)
            output, cursor = [], 0
            for start, end, replacement in item["edits"]:
                require(type(start) is int and type(end) is int and cursor <= start <= end <= len(lines) and isinstance(replacement, str), "Invalid source edit")
                output.extend(lines[cursor:start]); output.append(replacement); cursor = end
            output.extend(lines[cursor:])
            raw = "".join(output).encode()
            actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            require(actual == item["sha"], "Reviewed blob mismatch: " + path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            destination.chmod(0o755 if item["mode"] == "100755" else 0o644)
            git("add", "--", path)
        for item in recipes:
            run(sys.executable, "-m", "pinelib.abi", "build")
            require(git("hash-object", item["path"], text=True).strip() == item["sha"], "Generated artifact mismatch")
            git("add", "--", item["path"])
        require(git("write-tree", text=True).strip() == commit["tree"], "Reviewed tree mismatch")
        raw = commit["raw_commit"].encode()
        headers = raw.split(b"\n\n", 1)[0].decode().splitlines()
        require(headers[0] == "tree " + commit["tree"] and [h for h in headers if h.startswith("parent ")] == ["parent " + commit["parent"]], "Reviewed commit header mismatch")
        stored = git("hash-object", "-t", "commit", "-w", "--stdin", input=raw).decode().strip()
        require(stored == commit["sha"], "Reviewed commit mismatch")
        git("reset", "--hard", stored)
    require(git("rev-parse", "HEAD", text=True).strip() == submission["head"], "Wrong final candidate")
    git("diff", "--check", series["base"], "HEAD")
    (evidence / "head").write_text(submission["head"])
    git("update-ref", "refs/heads/reviewed-source", submission["head"])
    git("bundle", "create", str(evidence / "reviewed.bundle"), "reviewed-source")


def publish(evidence: Path) -> None:
    submission = json.loads((evidence / "submission.json").read_text())
    check_remote(submission)
    git("fetch", str(evidence / "reviewed.bundle"), "reviewed-source")
    actual = git("rev-parse", "FETCH_HEAD", text=True).strip()
    require(actual == submission["head"], "Evidence head mismatch")
    git("push", "origin", actual + ":refs/heads/" + submission["target"])
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as report:
        report.write("Published exact reviewed candidate `" + actual + "`. Functional tests and builds passed on Python 3.11/3.13. Not TradingView parity or coverage-threshold approval.\n")


if __name__ == "__main__":
    mode, evidence = sys.argv[1], Path(sys.argv[2]).resolve()
    if mode == "reconstruct":
        reconstruct(Path(sys.argv[3]), evidence)
    elif mode == "publish":
        publish(evidence)
    else:
        raise SystemExit("Expected reconstruct or publish")
