from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "fixtures" / "tradingview" / "cases.json"
VALID_STATUSES = {"oracle_verified", "golden_synthetic", "pending_external_oracle"}


def load_cases() -> dict[str, object]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def main() -> int:
    manifest = load_cases()
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise SystemExit("TradingView cases manifest must contain a cases list")
    oracle_verified = 0
    pending = 0
    for case in cases:
        if not isinstance(case, dict):
            raise SystemExit("Every TradingView case must be an object")
        status = case.get("status")
        case_id = case.get("id")
        if status not in VALID_STATUSES:
            raise SystemExit(f"Invalid status for case {case_id!r}: {status!r}")
        if status == "oracle_verified":
            oracle_verified += 1
            case_dir = CASES_PATH.parent / str(case_id)
            missing = [name for name in case.get("required_files", []) if not (case_dir / str(name)).is_file()]
            if missing:
                raise SystemExit(f"Oracle-verified case {case_id!r} is missing files: {missing}")
        if status == "pending_external_oracle":
            pending += 1
    print(json.dumps({"oracle_verified": oracle_verified, "pending_external_oracle": pending}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
