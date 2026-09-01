from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pinelib.errors import PL_RUNTIME_VERSION_UNSUPPORTED, PineRuntimeError

_CANONICAL_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")

PineVersion = Literal[1, 2, 3, 4, 5, 6]
VersionSource = Literal["compiler_annotation", "tradingview_default_v1"]


@dataclass(frozen=True, slots=True)
class RuntimeLanguageContext:
    pine_version: PineVersion
    spec_revision: str
    profile_id: str
    profile_hash: str
    version_source: VersionSource

    def __post_init__(self) -> None:
        if self.pine_version not in {1, 2, 3, 4, 5, 6}:
            raise PineRuntimeError(
                "unsupported Pine version", code=PL_RUNTIME_VERSION_UNSUPPORTED
            )
        if not self.spec_revision or not self.profile_id:
            raise PineRuntimeError("language context identity is incomplete")
        if (
            type(self.profile_hash) is not str
            or _CANONICAL_SHA256.fullmatch(self.profile_hash) is None
        ):
            raise PineRuntimeError("profile_hash must be canonical sha256")

    def identity(self) -> dict[str, object]:
        return {
            "pine_version": self.pine_version,
            "spec_revision": self.spec_revision,
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "version_source": self.version_source,
        }
