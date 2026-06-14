from __future__ import annotations

import sys
import types

from pinelib.compat.marketdata import (
    ContractBar,
    InstrumentKey,
    InvalidBarError,
    InvalidTimeframeError,
    Timeframe,
    parse_timeframe,
)


def pytest_configure() -> None:
    contracts = types.ModuleType("marketdata_provider.contracts")
    contracts.InstrumentKey = InstrumentKey
    contracts.Timeframe = Timeframe
    contracts.InvalidTimeframeError = InvalidTimeframeError
    contracts.parse_timeframe = parse_timeframe

    bar = types.ModuleType("marketdata_provider.contracts.bar")
    bar.Bar = ContractBar

    errors = types.ModuleType("marketdata_provider.contracts.errors")
    errors.InvalidBarError = InvalidBarError
    errors.InvalidTimeframeError = InvalidTimeframeError

    provider = types.ModuleType("marketdata_provider")
    provider.contracts = contracts

    sys.modules.setdefault("marketdata_provider", provider)
    sys.modules.setdefault("marketdata_provider.contracts", contracts)
    sys.modules.setdefault("marketdata_provider.contracts.bar", bar)
    sys.modules.setdefault("marketdata_provider.contracts.errors", errors)
