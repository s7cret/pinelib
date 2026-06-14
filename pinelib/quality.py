from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    digest: str
    locations: list[str]


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    duplicate_group_count: int
    groups: list[DuplicateGroup]


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    max_lines: int
    oversized_count: int
    oversized: list[dict[str, int | str]]


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    ]


def duplicates(root: str | Path) -> DuplicateReport:
    base = Path(root)
    seen: dict[str, list[str]] = {}
    for file_path in _python_files(base):
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                # Ignore tiny one-line helpers/properties. They are usually expected Python
                # protocol boilerplate rather than meaningful copy/paste implementation.
                if len(getattr(node, "body", ())) < 4:
                    continue
                normalized = ast.dump(node, include_attributes=False)
                digest = hashlib.sha256(normalized.encode()).hexdigest()
                seen.setdefault(digest, []).append(f"{file_path}:{node.lineno}:{node.name}")
    groups = [
        DuplicateGroup(digest, locations)
        for digest, locations in seen.items()
        if len(locations) > 1
    ]
    groups.sort(key=lambda group: group.locations)
    return DuplicateReport(len(groups), groups)


def architecture(root: str | Path, *, max_lines: int) -> ArchitectureReport:
    oversized: list[dict[str, int | str]] = []
    base = Path(root)
    for file_path in _python_files(base):
        lines = file_path.read_text(encoding="utf-8").count("\n") + 1
        if lines > max_lines:
            oversized.append({"path": str(file_path), "lines": lines})
    return ArchitectureReport(
        max_lines=max_lines, oversized_count=len(oversized), oversized=oversized
    )


def _emit(payload: Any, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(asdict(payload), indent=2, sort_keys=True))
    else:
        data = asdict(payload)
        for key, value in data.items():
            print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PineLib quality gates")
    parser.add_argument("command", choices=("duplicates", "architecture"))
    parser.add_argument("root", nargs="?", default="pinelib")
    parser.add_argument("--max-lines", type=int, default=700)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "duplicates":
        report = duplicates(args.root)
        _emit(report, json_output=args.json)
        return 1 if report.duplicate_group_count else 0
    report = architecture(args.root, max_lines=args.max_lines)
    _emit(report, json_output=args.json)
    return 1 if report.oversized_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
