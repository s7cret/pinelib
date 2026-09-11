# Coordinated entry-rule qualifiers — 2026-09-11

The published producer and host already admit fixed-per-run `input`/`simple`
values for `strategy.risk.allow_entry_in` and `strategy.risk.max_position_size`.
The raw target retained the frozen source surface's older `const` ceilings. With
lossless target qualification this stale metadata would reject existing supported
calls such as `max_position_size(input.int(2))`.

The audited projection updates **only** those two modern function parameter
ceilings from const to simple. It does not modify the frozen source catalogue,
other risk rules, broker behavior, numerical outputs, signatures, aliases or
runtime invocation. This alignment reflects the already verified producer/host
subset, not new independent TradingView execution evidence.

`tests/fixtures/entry_risk_qualifier_delta.json` records the original publication
base, complete before/after rows, expected content identity and the unchanged
remainder hash. Expected metadata was obtained from the published Git manifest
plus two literal edits, **not** by accepting generated output as a new oracle.
The regenerated materialized manifest must equal that independent composition.

Other metadata guard snapshots include the whole target or all unrelated rows.
Their identity hashes were explicitly rebased for this additive change; their
selected row expectations, test IDs and numerical fixture bytes were preserved.
The identity-only rebaseline is a separate commit. Earlier failed test output is
retained in the delivery evidence. This does not relax the materialized-manifest
check or permit silent metadata changes in future work.

The raw schema remains v2 but its content identity changes. Update the coordinated
compiler/host/worker source set and regenerate compiled artifacts. This document
is not an acceptance receipt for full Stage 2 or a production installer.
