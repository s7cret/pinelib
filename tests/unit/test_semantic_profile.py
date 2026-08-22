"""V5-SEM-001: SemanticProfile is fail-closed and drives security offset."""

from __future__ import annotations

import pytest
from openpine_contracts import SemanticProfile

from pinelib import (
    Bar,
    InMemoryDataProvider,
    PineRuntime,
    RuntimeConfig,
    SymbolInfo,
    TimeframeInfo,
    is_na,
    security,
)
from pinelib.core.semantic_profile import (
    SemanticProfileError,
    resolve_semantic_profile,
    security_lookup_index,
)
from pinelib.errors import PL_SEMANTIC_PROFILE_REQUIRED, PL_UNKNOWN_SEMANTIC_PROFILE


def _bars(times: list[int], tf_ms: int, closes: list[float] | None = None) -> list[Bar]:
    values = closes or [float(i + 1) for i in range(len(times))]
    return [
        Bar(time=t, time_close=t + tf_ms - 1, open=v, high=v, low=v, close=v)
        for t, v in zip(times, values, strict=True)
    ]


def test_runtime_config_uses_contracts_enum_not_local_literal() -> None:
    assert RuntimeConfig().semantic_profile is SemanticProfile.LEGACY_4X
    cfg = RuntimeConfig(semantic_profile=SemanticProfile.STRICT_5X)
    assert cfg.semantic_profile is SemanticProfile.STRICT_5X
    assert isinstance(cfg.semantic_profile, SemanticProfile)


def test_unknown_and_missing_profile_fail_closed() -> None:
    with pytest.raises(SemanticProfileError, match=PL_UNKNOWN_SEMANTIC_PROFILE):
        resolve_semantic_profile("not_a_profile")
    with pytest.raises(SemanticProfileError, match=PL_SEMANTIC_PROFILE_REQUIRED):
        resolve_semantic_profile(None, source="generated_artifact.v2")


def test_legacy_artifact_reader_assigns_legacy_explicitly() -> None:
    profile = resolve_semantic_profile(None, source="openpine.frontend.v1")
    assert profile is SemanticProfile.LEGACY_4X


def test_security_offset_differs_by_profile() -> None:
    chart = _bars([0, 3_600_000, 7_200_000], 3_600_000)
    requested = _bars([0, 7_200_000], 7_200_000, [100.0, 200.0])
    provider = InMemoryDataProvider({("TEST:AAA", "60"): chart, ("TEST:BBB", "120"): requested})

    def _run(profile: SemanticProfile) -> list[object]:
        rt = PineRuntime(
            SymbolInfo("TEST:AAA", timezone="UTC"),
            TimeframeInfo.from_string("60"),
            data_provider=provider,
            config=RuntimeConfig(semantic_profile=profile),
        )
        out: list[object] = []
        for bar in chart:
            rt.begin_bar(bar)
            out.append(
                security(
                    "TEST:BBB",
                    "120",
                    lambda child: float(child.close[0]),
                    runtime=rt,
                    state_id=f"sem-{profile.value}",
                )
            )
            rt.end_bar()
        return out

    legacy = _run(SemanticProfile.LEGACY_4X)
    strict = _run(SemanticProfile.STRICT_5X)
    assert is_na(legacy[0])
    assert legacy != strict


def test_security_lookup_index_is_profile_explicit() -> None:
    class _RT:
        bar_index = 2
        current_bar = object()
        config = RuntimeConfig(semantic_profile=SemanticProfile.LEGACY_4X)

    assert security_lookup_index(_RT()) == 3
    _RT.config = RuntimeConfig(semantic_profile=SemanticProfile.STRICT_5X)
    assert security_lookup_index(_RT()) == 2
