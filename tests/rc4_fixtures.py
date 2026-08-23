from __future__ import annotations

from typing import Any

from openpine_contracts import seal_content_hash, validate_payload

COMMIT = "801b908e0ba53d1387cfd032cb6d29aa53ba0ca0"
HASH_A = "sha256:" + ("a" * 64)
HASH_B = "sha256:" + ("b" * 64)
HASH_C = "sha256:" + ("c" * 64)
HASH_D = "sha256:" + ("d" * 64)
STACK_COMPONENTS = (
    "openpine-contracts",
    "marketdata-provider",
    "pinelib",
    "pine2ast",
    "ast2python",
    "backtest_engine",
    "optimizer",
    "openpine",
)


def execution_context(
    *,
    run_id: str = "run-1",
    strategy_id: str = "strat-1",
    series_id: str = "series-1",
    instrument_id: str = "NASDAQ:AAPL",
    exchange: str = "NASDAQ",
    market: str = "stock",
    symbol: str = "AAPL",
    timeframe: str = "60",
    timezone: str = "UTC",
    currency: str = "USD",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_id": "openpine.execution_context.v1",
        "schema_version": "1.0.0",
        "producer": "pinelib-tests",
        "producer_version": "5.0.0-rc.4",
        "producer_commit": COMMIT,
        "stack_id": HASH_D,
        "created_at_utc_ms": 0,
        "serializer_id": "openpine.canonical.json.v1",
        "content_hash_alg": "sha256",
        "run_id": run_id,
        "strategy_id": strategy_id,
        "session_id": f"session:{run_id}",
        "stack_manifest_hash": HASH_D,
        "wheel_identities": [
            {"name": name, "version": "5.0.0rc4", "content_hash": HASH_B}
            for name in STACK_COMPONENTS
        ],
        "schema_hashes": {
            "openpine.intent.v2": HASH_B,
            "openpine.execution_context.v1": HASH_C,
        },
        "generated_artifact_hash": HASH_B,
        "source_hash": HASH_C,
        "emitted_module_hash": HASH_D,
        "data_snapshot_hash": HASH_A,
        "series_id": series_id,
        "instrument_id": instrument_id,
        "exchange": exchange,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": timezone,
        "currency": currency,
        "mintick": "0.01",
        "pointvalue": "1",
        "session_policy": "regular",
        "semantic_profile": "strict_5x",
        "finality_policy": "CLOSED_BAR_ONLY",
        "warmup_policy": "CALC_ONLY",
        "score_policy": "ALL_BARS",
        "end_policy": "LIQUIDATE_ON_LAST_BAR",
        "capabilities": ["closed_bar", "checkpoint_v1"],
        "producer_commits": {name: COMMIT for name in STACK_COMPONENTS},
    }
    payload.update(overrides)
    sealed = seal_content_hash(payload, schema_id="openpine.execution_context.v1")
    validate_payload("openpine.execution_context.v1", sealed)
    return sealed


def known_source_span(
    *,
    start_offset: int = 10,
    end_offset: int = 20,
    start_line: int = 2,
    start_col: int = 3,
    end_line: int = 2,
    end_col: int = 13,
) -> dict[str, Any]:
    return {
        "known": True,
        "source_hash": HASH_C,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "start_line": start_line,
        "start_col": start_col,
        "end_line": end_line,
        "end_col": end_col,
    }
