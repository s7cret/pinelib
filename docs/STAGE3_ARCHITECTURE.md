# Stage 3 architecture (baseline retained in the Stage 4 tree)

## Generated ABI boundary

Generated modules call concrete functions under `pinelib.abi`. Every locally classified supported target row has one importable callable. Runtime name lookup and generic dispatch are intentionally absent. Reflection is limited to the offline manifest builder, where it verifies exported signatures; it does not select runtime semantics.

## Stateful kernels

All TA kernels accept a `RuntimeTransaction` and a compiler-provided `state_id`. State is held in typed slot payloads inside the transaction. A failed callback discards working kernel state together with series/reference/event mutations. Checkpoint serialization uses portable JSON values and deterministic hashes.

Tuple-returning kernels expose immutable records (`MacdResult`, `BandsResult`, `DmiResult`, and `SupertrendResult`) so return arity is not guessed from names at the call site.

## Time and sessions

Time-zone data is loaded from the exact `tzdata==2026.2` package by resource path and `ZoneInfo.from_file`. This prevents changes in a host OS time-zone database from silently changing runtime behavior. Invalid or absent time zones fail closed. Session parsing handles explicit day sets, version-dependent default day sets, and overnight intervals.

## References

`RuntimeReferenceHeap` assigns deterministic integer handles within runtime state. Assignment preserves handles; copy allocates a distinct handle and detached payload. Arrays, maps, matrices, UDT records and enum values validate types and bounds at their ABI boundary. Heap revisions participate in transactions and checkpoints; Python object identity is never persisted.

## Visuals and alerts

Visual and alert calls append immutable events carrying source span, callback sequence, phase, invocation ordinal, event identity and delivery identity. Aborted callbacks discard their events. PineLib does not render visual objects and does not deliver notifications.

## Explicit non-goals of this stage

At the Stage 3 boundary this source did not implement the Request Engine. The current Stage 4 tree adds it as documented in `STAGE4_ARCHITECTURE.md`; Stage 5 broker projection/strategy integration, rendering, notification delivery, order matching, fills, positions, P&L, and compiler lowering remain out of scope.
