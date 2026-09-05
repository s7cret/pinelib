from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from pinelib.errors import PL_ABI_MANIFEST, PineRuntimeError
from pinelib.state.checkpoint import sha


@lru_cache(maxsize=1)
def load_target_manifest() -> dict[str, object]:
    resource = files("pinelib.abi").joinpath("target_manifest.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PineRuntimeError(
            "target manifest must be an object", code=PL_ABI_MANIFEST
        )
    content_hash = data.get("content_hash")
    body = {key: value for key, value in data.items() if key != "content_hash"}
    if content_hash != sha(body):
        raise PineRuntimeError("target manifest hash mismatch", code=PL_ABI_MANIFEST)
    classification = data.get("classification")
    if not isinstance(classification, dict) or classification.get("unknown") != 0:
        raise PineRuntimeError(
            "target manifest contains unknown rows", code=PL_ABI_MANIFEST
        )

    # Hash validity alone does not make a self-consistent but semantically forged
    # manifest admissible.  Rebuild the canonical ABI contract and require exact
    # schema, row, callable-signature, classification, and count equality.
    from pinelib.abi.builder import build_manifest

    if data != build_manifest():
        raise PineRuntimeError(
            "target manifest semantic content mismatch", code=PL_ABI_MANIFEST
        )
    return data
