from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pinelib.state.checkpoint import canonical_json, sha

CATEGORIES = ("functions", "methods", "variables", "constants", "types")
PREFIX = {
    "functions": "function",
    "methods": "method",
    "variables": "variable",
    "constants": "constant",
    "types": "type",
}


def build_official_surface(pine2ast_package: Path) -> dict[str, Any]:
    index = json.loads(
        (
            pine2ast_package
            / "reference_catalog"
            / "official_pine_v6_reference_index.json"
        ).read_text(encoding="utf-8")
    )
    packs = {
        version: json.loads(
            (
                pine2ast_package
                / "catalog_data"
                / "packs"
                / f"pine_v{version}.pack.json"
            ).read_text(encoding="utf-8")
        )
        for version in range(1, 7)
    }
    rows: list[dict[str, Any]] = []
    for category in CATEGORIES:
        for name in index["categories"][category]:
            entry = packs[6]["sections"][category].get(name, {})
            parameters: list[dict[str, Any]] = []
            if category in {"functions", "methods"}:
                for raw_parameter in entry.get("parameters", []):
                    if not isinstance(raw_parameter, dict):
                        continue
                    parameter = dict(raw_parameter)
                    parameter.setdefault("required", False)
                    parameter.setdefault("type", "unknown")
                    parameter.setdefault("qualifier_max", "series")
                    parameters.append(parameter)
            row = {
                "category": category,
                "name": name,
                # Build from the exact catalog key. Some upstream metadata fields
                # encode '<type>' as the literal text 'u003c...u003e'.
                "symbol_id": f"pine:{PREFIX[category]}:{name}",
                "supported_versions": [
                    version
                    for version, pack in packs.items()
                    if name in pack["sections"].get(category, {})
                ],
                "parameters": parameters,
                "receiver_type": entry.get("receiver_type"),
                "returns": entry.get("returns") or entry.get("type") or "unknown",
            }
            # Stage 2.1 extends only the input-family projection. Keeping the
            # accepted compact shape for unrelated rows prevents a catalog-input
            # change from silently re-baselining every runtime contract.
            if category == "functions" and (name == "input" or name.startswith("input.")):
                row.update(
                    {
                        "overloads": [
                            {
                                "overload_id": overload.get("overload_id"),
                                "parameters": [
                                    {
                                        **dict(parameter),
                                        "required": dict(parameter).get("required", False),
                                        "type": dict(parameter).get("type", "unknown"),
                                        "qualifier_max": dict(parameter).get(
                                            "qualifier_max", "series"
                                        ),
                                    }
                                    for parameter in overload.get("parameters", [])
                                    if isinstance(parameter, dict)
                                ],
                                "returns": overload.get("returns")
                                or entry.get("returns")
                                or entry.get("type")
                                or "unknown",
                                "return_qualifier": overload.get("return_qualifier"),
                            }
                            for overload in entry.get("overloads", [])
                            if isinstance(overload, dict)
                        ],
                        "return_qualifier": entry.get("return_qualifier"),
                        "return_rule_id": entry.get("return_rule_id"),
                        "return_qualifier_rule_id": entry.get(
                            "return_qualifier_rule_id"
                        ),
                        "parameter_type_rule_id": entry.get("parameter_type_rule_id"),
                        "input_contract_revision": entry.get(
                            "input_contract_revision"
                        ),
                    }
                )
            rows.append(row)
    rows.sort(key=lambda row: (row["category"], row["name"]))
    counts = {
        category: sum(row["category"] == category for row in rows)
        for category in CATEGORIES
    }
    body: dict[str, Any] = {
        "schema_id": "pinelib.official_pine_v6_surface.v1",
        "schema_version": "1.0.0",
        "source_index_content_hash": sha(index),
        "source_pack_hashes": {
            f"v{version}": packs[version]["content_hash"] for version in range(1, 7)
        },
        "counts": counts,
        "denominator": len(rows),
        "rows": rows,
    }
    return {**body, "content_hash": sha(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pine2ast-package", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[1]
        / "pinelib"
        / "abi"
        / "official_pine_v6_surface.json",
    )
    args = parser.parse_args()
    surface = build_official_surface(args.pine2ast_package)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(surface) + b"\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "denominator": surface["denominator"],
                "content_hash": surface["content_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
