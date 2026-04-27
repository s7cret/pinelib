from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "fixtures" / "tradingview" / "cases.json"
VALID_STATUSES = {"oracle_verified", "golden_synthetic", "platform_blocked"}


def load_cases() -> dict[str, object]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _require_files(case_dir: Path, case_id: object, files: object, *, label: str) -> None:
    if not isinstance(files, list):
        raise SystemExit(f"Case {case_id!r} {label} must be a list")
    missing = [name for name in files if not (case_dir / str(name)).is_file()]
    if missing:
        raise SystemExit(f"Case {case_id!r} is missing {label}: {missing}")


def main() -> int:
    manifest = load_cases()
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise SystemExit("TradingView cases manifest must contain a cases list")
    counts = {"oracle_verified": 0, "golden_synthetic": 0, "platform_blocked": 0, "pending_external_oracle": 0}
    for case in cases:
        if not isinstance(case, dict):
            raise SystemExit("Every TradingView case must be an object")
        status = case.get("status")
        case_id = case.get("id")
        if status == "pending_external_oracle":
            raise SystemExit(f"Pending TradingView oracle case is not allowed in final suite: {case_id!r}")
        if status not in VALID_STATUSES:
            raise SystemExit(f"Invalid status for case {case_id!r}: {status!r}")
        counts[str(status)] += 1
        case_dir = CASES_PATH.parent / str(case_id)
        _require_files(case_dir, case_id, case.get("evidence_files", []), label="evidence files")
        if status == "oracle_verified":
            if not str(case.get("oracle_source", "")).startswith("TradingView"):
                raise SystemExit(f"Oracle-verified case {case_id!r} must name a TradingView oracle_source")
            _require_files(case_dir, case_id, case.get("required_files", []), label="required files")
        elif status == "platform_blocked":
            if not str(case.get("blocked_reason", "")).strip():
                raise SystemExit(f"Platform-blocked case {case_id!r} must include blocked_reason")
            if not str(case.get("blocked_by", "")).strip():
                raise SystemExit(f"Platform-blocked case {case_id!r} must include blocked_by")
            present_required = [name for name in case.get("required_files", []) if (case_dir / str(name)).exists()]
            if present_required:
                raise SystemExit(
                    f"Platform-blocked case {case_id!r} must not carry unverified oracle outputs: {present_required}"
                )
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
