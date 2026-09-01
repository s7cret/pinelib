from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

_GENERIC_DISPATCH_NAMES = {
    "dispatch",
    "execute_namespace",
    "execute_operation",
    "invoke",
}
_BROKER_MODEL_NAMES = {"Fill", "Trade", "_OpenLot"}
_FORBIDDEN_TOKENS = (
    "pending_orders",
    "_between_bars",
    "ohlc_path",
    "legacy_4x",
    "strict_5x",
    "RuntimeConfig.extra",
    "_effective_close_time",
    "provider.__class__.__module__",
    "__class__.__module__",
    '"binance"',
    "'binance'",
    '"spot"',
    "'spot'",
)


def scan(root: Path, root_argument: str) -> dict[str, object]:
    violations: list[dict[str, object]] = []
    files = sorted(root.rglob("*.py"))
    for source in files:
        relative = source.relative_to(root).as_posix()
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name in _GENERIC_DISPATCH_NAMES
            ):
                violations.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "kind": "generic_dispatch",
                        "name": node.name,
                    }
                )
            if isinstance(node, ast.ClassDef) and node.name in _BROKER_MODEL_NAMES:
                violations.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "kind": "broker_model",
                        "name": node.name,
                    }
                )
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {
                    "id",
                    "deepcopy",
                }:
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "kind": "forbidden_call",
                            "name": node.func.id,
                        }
                    )
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "deepcopy"
                ):
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "kind": "forbidden_call",
                            "name": "deepcopy",
                        }
                    )
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                module = getattr(node, "module", None)
                if "pickle" in names or module == "pickle":
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "kind": "pickle_import",
                        }
                    )
        for token in _FORBIDDEN_TOKENS:
            if token in text:
                violations.append(
                    {
                        "path": relative,
                        "line": 0,
                        "kind": "forbidden_token",
                        "name": token,
                    }
                )
        if "inspect.signature" in text and relative != "abi/builder.py":
            violations.append(
                {
                    "path": relative,
                    "line": 0,
                    "kind": "runtime_reflection",
                    "name": "inspect.signature",
                }
            )
    return {
        "schema_id": "pinelib.stage4.forbidden_scan.v1",
        "command": ["tools/forbidden_scan.py", "--root", root_argument],
        "scan_root": root_argument,
        "files_scanned": len(files),
        "violations": violations,
        "pass": not violations,
        "allowances": [
            {
                "path": "abi/builder.py",
                "reason": "offline build-time signature verification only",
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    arguments = parser.parse_args()
    root = Path(arguments.root)
    if not root.is_dir():
        parser.error(f"scan root is not a directory: {arguments.root}")
    result = scan(root, arguments.root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
