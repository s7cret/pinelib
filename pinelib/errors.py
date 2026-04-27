from __future__ import annotations

from dataclasses import dataclass
from typing import Final


PL_UNSUPPORTED_NESTED_SECURITY: Final[str] = "PL_UNSUPPORTED_NESTED_SECURITY"
PL_WARNING_EXIT_QTY_REDUCED: Final[str] = "PL_WARNING_EXIT_QTY_REDUCED"
PL_DATA_FORMAT_ERROR: Final[str] = "PL_DATA_FORMAT_ERROR"
PL_UNSUPPORTED_STRATEGY_SETTING: Final[str] = "PL_UNSUPPORTED_STRATEGY_SETTING"
PL_MISSING_INTRABAR_DATA: Final[str] = "PL_MISSING_INTRABAR_DATA"
PL_WARNING_BAR_MAGNIFIER_FALLBACK: Final[str] = "PL_WARNING_BAR_MAGNIFIER_FALLBACK"
PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK: Final[str] = "PL_WARNING_CALC_ON_EVERY_TICK_FALLBACK"
PL_INPUT_VALIDATION_ERROR: Final[str] = "PL_INPUT_VALIDATION_ERROR"
PL_SESSION_PARSE_ERROR: Final[str] = "PL_SESSION_PARSE_ERROR"
PL_REFERENCE_HISTORY_UNSUPPORTED: Final[str] = "PL_REFERENCE_HISTORY_UNSUPPORTED"
PL_MARGIN_FIELDS_DIAGNOSTIC: Final[str] = "PL_MARGIN_FIELDS_DIAGNOSTIC"


@dataclass(frozen=True, slots=True)
class ErrorContext:
    function_name: str | None = None
    bar_index: int | None = None
    source_map: str | None = None
    remedy: str | None = None


class PineRuntimeError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: ErrorContext | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context

    def __str__(self) -> str:
        details: list[str] = [self.message]
        if self.code:
            details.append(f"code={self.code}")
        if self.context:
            if self.context.function_name:
                details.append(f"function={self.context.function_name}")
            if self.context.bar_index is not None:
                details.append(f"bar_index={self.context.bar_index}")
            if self.context.source_map:
                details.append(f"source_map={self.context.source_map}")
            if self.context.remedy:
                details.append(f"remedy={self.context.remedy}")
        return "; ".join(details)


class PineTypeError(PineRuntimeError):
    pass


class PineNAError(PineRuntimeError):
    pass


class PineHistoryError(PineRuntimeError):
    pass


class PineRequestError(PineRuntimeError):
    pass


class PineStrategyError(PineRuntimeError):
    pass


class PineUnsupportedFeatureError(PineRuntimeError):
    pass


class PineGoldenMismatchError(PineRuntimeError):
    pass


class PineDataFormatError(PineRuntimeError):
    def __init__(self, message: str, *, context: ErrorContext | None = None) -> None:
        super().__init__(message, code=PL_DATA_FORMAT_ERROR, context=context)


class PineSessionError(PineRuntimeError):
    def __init__(self, message: str, *, context: ErrorContext | None = None) -> None:
        super().__init__(message, code=PL_SESSION_PARSE_ERROR, context=context)

