from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "fixtures" / "tradingview" / "cases.json"
VALID_STATUSES = {"oracle_verified", "golden_synthetic", "platform_blocked"}
SUPPORTED_ASSERTION_KINDS = {"csv_column", "csv_rows", "json_value"}


def load_cases() -> dict[str, object]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("TradingView cases manifest must be a JSON object")
    return cast(dict[str, object], data)


def _require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label} must be a non-empty string")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SystemExit(f"{label} must be positive")
    return value


def _safe_fixture_path(fixture_dir: Path, value: object, *, label: str) -> Path:
    name = _require_string(value, label=label)
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"{label} must stay inside its evidence fixture: {name!r}")
    root = fixture_dir.resolve(strict=False)
    candidate = fixture_dir / relative
    current = fixture_dir
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise SystemExit(f"{label} must not use symlinks: {name!r}")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"{label} must stay inside its evidence fixture: {name!r}") from exc
    return candidate


def _require_files(case_dir: Path, fixture_id: str, files: object, *, label: str) -> list[str]:
    if not isinstance(files, list):
        raise SystemExit(f"Fixture {fixture_id!r} {label} must be a list")
    names: list[str] = []
    for index, value in enumerate(files):
        path = _safe_fixture_path(
            case_dir,
            value,
            label=f"Fixture {fixture_id!r} {label}[{index}]",
        )
        names.append(str(value))
        if not path.is_file():
            raise SystemExit(f"Fixture {fixture_id!r} is missing {label}: {value!r}")
    return names


def _strict_target_keys(
    target: Mapping[str, object], *, assertion_id: str, expected: set[str]
) -> None:
    actual = set(target)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise SystemExit(
            f"Assertion {assertion_id!r} has invalid target fields; "
            f"missing={missing}, unknown={unknown}"
        )


def _evaluate_csv_column(
    source_path: Path, target: Mapping[str, object], *, assertion_id: str
) -> None:
    _strict_target_keys(
        target,
        assertion_id=assertion_id,
        expected={
            "kind",
            "source",
            "column",
            "min_rows",
            "min_non_empty",
            "min_distinct",
        },
    )
    column = _require_string(target.get("column"), label=f"Assertion {assertion_id!r} column")
    min_rows = _require_positive_int(
        target.get("min_rows"), label=f"Assertion {assertion_id!r} min_rows"
    )
    min_non_empty = _require_positive_int(
        target.get("min_non_empty"),
        label=f"Assertion {assertion_id!r} min_non_empty",
    )
    min_distinct = _require_positive_int(
        target.get("min_distinct"),
        label=f"Assertion {assertion_id!r} min_distinct",
    )
    if min_non_empty > min_rows or min_distinct > min_non_empty:
        raise SystemExit(f"Assertion {assertion_id!r} has impossible CSV minimums")

    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise SystemExit(f"Assertion {assertion_id!r} missing CSV column {column!r}")
        rows = list(reader)
    values = [row[column] for row in rows if row[column].strip()]
    if len(rows) < min_rows:
        raise SystemExit(
            f"Assertion {assertion_id!r} expected at least {min_rows} rows, got {len(rows)}"
        )
    if len(values) < min_non_empty:
        raise SystemExit(
            f"Assertion {assertion_id!r} expected at least {min_non_empty} non-empty "
            f"{column!r} values, got {len(values)}"
        )
    distinct = len(set(values))
    if distinct < min_distinct:
        raise SystemExit(
            f"Assertion {assertion_id!r} expected at least {min_distinct} distinct "
            f"{column!r} values, got {distinct}"
        )


def _string_mapping(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise SystemExit(f"{label} must be a non-empty object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise SystemExit(f"{label} keys must be non-empty strings")
        if not isinstance(item, (str, int, float, bool)):
            raise SystemExit(f"{label}[{key!r}] must be a scalar")
        result[key] = str(item)
    return result


def _evaluate_csv_rows(
    source_path: Path, target: Mapping[str, object], *, assertion_id: str
) -> None:
    _strict_target_keys(
        target,
        assertion_id=assertion_id,
        expected={"kind", "source", "where", "expected", "count"},
    )
    where = _string_mapping(target.get("where"), label=f"Assertion {assertion_id!r} where")
    expected = _string_mapping(target.get("expected"), label=f"Assertion {assertion_id!r} expected")
    count = _require_positive_int(target.get("count"), label=f"Assertion {assertion_id!r} count")
    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        referenced = set(where) | set(expected)
        missing = sorted(referenced - fieldnames)
        if missing:
            raise SystemExit(f"Assertion {assertion_id!r} missing CSV columns: {missing}")
        rows = list(reader)
    matched = [
        row for row in rows if all(str(row.get(key, "")) == value for key, value in where.items())
    ]
    if len(matched) != count:
        raise SystemExit(
            f"Assertion {assertion_id!r} expected {count} matching CSV rows, got {len(matched)}"
        )
    for row in matched:
        mismatches = {
            key: (value, row.get(key))
            for key, value in expected.items()
            if str(row.get(key, "")) != value
        }
        if mismatches:
            raise SystemExit(
                f"Assertion {assertion_id!r} CSV row values did not match: {mismatches}"
            )


def _resolve_json_path(payload: object, path: Sequence[object], *, assertion_id: str) -> object:
    current = payload
    for component in path:
        if isinstance(current, dict) and isinstance(component, str) and component in current:
            current = current[component]
            continue
        if (
            isinstance(current, list)
            and isinstance(component, int)
            and not isinstance(component, bool)
            and 0 <= component < len(current)
        ):
            current = current[component]
            continue
        raise SystemExit(
            f"Assertion {assertion_id!r} cannot resolve JSON path component {component!r}"
        )
    return current


def _evaluate_json_value(
    source_path: Path, target: Mapping[str, object], *, assertion_id: str
) -> None:
    _strict_target_keys(
        target,
        assertion_id=assertion_id,
        expected={"kind", "source", "path", "equals"},
    )
    path = target.get("path")
    if not isinstance(path, list) or not path:
        raise SystemExit(f"Assertion {assertion_id!r} JSON path must be a non-empty list")
    if any(
        not isinstance(component, (str, int)) or isinstance(component, bool) for component in path
    ):
        raise SystemExit(f"Assertion {assertion_id!r} JSON path components must be strings or ints")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    actual = _resolve_json_path(payload, path, assertion_id=assertion_id)
    expected = target["equals"]
    if actual != expected:
        raise SystemExit(
            f"Assertion {assertion_id!r} expected JSON value {expected!r}, got {actual!r}"
        )


def _evaluate_target(fixture_dir: Path, target: Mapping[str, object], *, assertion_id: str) -> None:
    kind = _require_string(target.get("kind"), label=f"Assertion {assertion_id!r} kind")
    if kind not in SUPPORTED_ASSERTION_KINDS:
        raise SystemExit(f"Unsupported assertion kind for {assertion_id!r}: {kind!r}")
    source_path = _safe_fixture_path(
        fixture_dir,
        target.get("source"),
        label=f"Assertion {assertion_id!r} source",
    )
    if not source_path.is_file():
        raise SystemExit(
            f"Assertion {assertion_id!r} evidence source is missing: {source_path.name}"
        )
    if kind == "csv_column":
        _evaluate_csv_column(source_path, target, assertion_id=assertion_id)
    elif kind == "csv_rows":
        _evaluate_csv_rows(source_path, target, assertion_id=assertion_id)
    else:
        _evaluate_json_value(source_path, target, assertion_id=assertion_id)


def validate_manifest(manifest: Mapping[str, object], *, fixtures_root: Path) -> dict[str, int]:
    if manifest.get("schema_version") != "2.0":
        raise SystemExit("TradingView cases manifest schema_version must be '2.0'")
    fixtures = manifest.get("fixtures")
    cases = manifest.get("cases")
    if not isinstance(fixtures, dict) or not fixtures:
        raise SystemExit("TradingView cases manifest must contain a fixtures object")
    if not isinstance(cases, list):
        raise SystemExit("TradingView cases manifest must contain a cases list")
    minimum_assertions = _require_positive_int(
        manifest.get("minimum_assertions"), label="minimum_assertions"
    )
    if len(cases) < minimum_assertions:
        raise SystemExit(
            f"TradingView suite requires at least {minimum_assertions} assertions, got {len(cases)}"
        )

    counts = {
        "oracle_verified": 0,
        "golden_synthetic": 0,
        "platform_blocked": 0,
        "pending_external_oracle": 0,
        "assertions_evaluated": 0,
        "evidence_fixtures": 0,
    }
    seen_case_ids: set[str] = set()
    seen_assertion_ids: set[str] = set()
    seen_targets: set[str] = set()
    referenced_fixtures: set[str] = set()

    for raw_case in cases:
        if not isinstance(raw_case, dict):
            raise SystemExit("Every TradingView case must be an object")
        case = cast(dict[str, object], raw_case)
        case_id = _require_string(case.get("id"), label="Case id")
        if case_id in seen_case_ids:
            raise SystemExit(f"Duplicate case id: {case_id!r}")
        seen_case_ids.add(case_id)
        assertion_id = _require_string(
            case.get("assertion_id"), label=f"Case {case_id!r} assertion_id"
        )
        if assertion_id in seen_assertion_ids:
            raise SystemExit(f"Duplicate assertion_id: {assertion_id!r}")
        seen_assertion_ids.add(assertion_id)

        status = case.get("status")
        if status == "pending_external_oracle":
            raise SystemExit(
                f"Pending TradingView oracle case is not allowed in final suite: {case_id!r}"
            )
        if not isinstance(status, str) or status not in VALID_STATUSES:
            raise SystemExit(f"Invalid status for case {case_id!r}: {status!r}")
        counts[status] += 1

        fixture_id = _require_string(case.get("fixture_id"), label=f"Case {case_id!r} fixture_id")
        fixture = fixtures.get(fixture_id)
        if not isinstance(fixture, dict):
            raise SystemExit(f"Case {case_id!r} references unknown fixture {fixture_id!r}")
        referenced_fixtures.add(fixture_id)
        fixture_dir = _safe_fixture_path(
            fixtures_root,
            fixture_id,
            label=f"Case {case_id!r} fixture_id",
        )
        required_files = fixture.get("required_files")
        evidence_files = _require_files(
            fixture_dir,
            fixture_id,
            fixture.get("evidence_files"),
            label="evidence files",
        )

        if status == "oracle_verified":
            if not str(fixture.get("oracle_source", "")).startswith("TradingView"):
                raise SystemExit(
                    f"Oracle fixture {fixture_id!r} must name a TradingView oracle_source"
                )
            required_names = _require_files(
                fixture_dir,
                fixture_id,
                required_files,
                label="required files",
            )
        elif status == "platform_blocked":
            if not str(case.get("blocked_reason", "")).strip():
                raise SystemExit(f"Platform-blocked case {case_id!r} must include blocked_reason")
            if not str(case.get("blocked_by", "")).strip():
                raise SystemExit(f"Platform-blocked case {case_id!r} must include blocked_by")
            if not isinstance(required_files, list):
                raise SystemExit(f"Fixture {fixture_id!r} required files must be a list")
            required_names = [str(value) for value in required_files]
            present_required = [
                name
                for name in required_names
                if _safe_fixture_path(
                    fixture_dir,
                    name,
                    label=f"Fixture {fixture_id!r} required file",
                ).exists()
            ]
            if present_required:
                raise SystemExit(
                    "Platform-blocked case "
                    f"{case_id!r} must not carry unverified oracle outputs: {present_required}"
                )
        else:
            required_names = _require_files(
                fixture_dir,
                fixture_id,
                required_files,
                label="required files",
            )

        target = case.get("target")
        if not isinstance(target, dict):
            raise SystemExit(f"Case {case_id!r} target must be an object")
        evidence_source = _require_string(
            case.get("evidence_source"), label=f"Case {case_id!r} evidence_source"
        )
        if target.get("source") != evidence_source:
            raise SystemExit(f"Case {case_id!r} evidence_source must equal target.source")
        if evidence_source not in set(required_names) | set(evidence_files):
            raise SystemExit(
                f"Case {case_id!r} evidence_source must be declared by fixture {fixture_id!r}"
            )
        target_signature = json.dumps(
            [fixture_id, evidence_source, target], sort_keys=True, separators=(",", ":")
        )
        if target_signature in seen_targets:
            raise SystemExit(f"Duplicate assertion target: {assertion_id!r}")
        seen_targets.add(target_signature)
        _evaluate_target(fixture_dir, target, assertion_id=assertion_id)
        counts["assertions_evaluated"] += 1

    unused_fixtures = sorted(set(fixtures) - referenced_fixtures)
    if unused_fixtures:
        raise SystemExit(f"TradingView manifest contains unused fixtures: {unused_fixtures}")
    counts["evidence_fixtures"] = len(referenced_fixtures)
    return counts


def main() -> int:
    manifest = load_cases()
    counts = validate_manifest(manifest, fixtures_root=CASES_PATH.parent)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
