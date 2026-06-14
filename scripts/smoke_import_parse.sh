#!/usr/bin/env bash
set -euo pipefail
PYTHON=${PYTHON:-python}
"$PYTHON" - <<'PY'
from pinelib import Bar, PineRuntime, StrategyContext, SymbolInfo, TimeframeInfo, run_generated_strategy

class Generated:
    def on_bar(self, runtime, strategy):
        strategy.entry("L", "long", qty=1)

runtime = PineRuntime(SymbolInfo("TEST:AAA"), TimeframeInfo.from_string("60"))
strategy = StrategyContext()
result = run_generated_strategy(
    Generated(),
    runtime,
    strategy,
    [Bar(0, 1, 1, 1, 1, time_close=3599999)],
)
assert result.report.order_intents[0]["id"] == "L"
print("pinelib smoke ok")
PY
