from __future__ import annotations

from pinelib.events import SourceSpan
from pinelib.input import InputRegistry, InputSpec
from pinelib.runtime import (
    CallbackFrame,
    InstrumentContext,
    RuntimeLanguageContext,
    RuntimePolicies,
    RuntimeSession,
    TimeframeContext,
)


def language(version: int = 6) -> RuntimeLanguageContext:
    return RuntimeLanguageContext(
        version,
        "2026-08-29",
        f"pine-v{version}",
        "sha256:" + "1" * 64,
        "compiler_annotation",
    )


def inputs() -> InputRegistry:
    return InputRegistry(
        [
            InputSpec("bool", "bool", True, False),
            InputSpec("int", "int", 2, 3, minimum=1, maximum=10, step=1),
            InputSpec("float", "float", 1.0, 1.5, minimum=0.0, maximum=2.0, step=0.5),
            InputSpec("string", "string", "a", "b", options=("a", "b")),
            InputSpec("time", "time", 0, 1_700_000_000_000),
            InputSpec("price", "price", 1.0, 2.5),
            InputSpec("symbol", "symbol", "X", "BINANCE:BTCUSDT"),
            InputSpec("timeframe", "timeframe", "60", "15"),
            InputSpec("session", "session", "0000-0000", "0900-1700:23456"),
            InputSpec("color", "color", "#000000", "#ffffff"),
            InputSpec("source", "source", "close", "hl2"),
        ]
    )


def session(
    version: int = 6,
    *,
    request_provider=None,
    policies: RuntimePolicies | None = None,
) -> RuntimeSession:
    return RuntimeSession(
        language(version),
        policies if policies is not None else RuntimePolicies(),
        inputs=inputs(),
        instrument=InstrumentContext(
            ticker="BTCUSDT",
            tickerid="BINANCE:BTCUSDT",
            prefix="BINANCE",
            currency="USDT",
            basecurrency="BTC",
            timezone="UTC",
            instrument_type="crypto",
            mintick=0.01,
            pointvalue=1.0,
            mincontract=0.001,
        ),
        timeframe=TimeframeContext.parse("15"),
        request_provider=request_provider,
    )


def transaction(index: int = 0, *, version: int = 6):
    runtime = session(version)
    tx = runtime.begin(CallbackFrame("HISTORICAL_EVAL", index, bar_index=index))
    return runtime, tx


def span() -> SourceSpan:
    return SourceSpan("sha256:" + "2" * 64, "strategy.pine", 1, 0, 1, 10)
