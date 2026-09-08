# TSI ratio and numerical state boundary

Pine 5/6 `ta.tsi` now returns the ratio of its existing doubly smoothed change
and absolute change. The old multiplication by 100 is retained only for earlier
versions. Computing the modern ratio directly also avoids the old intermediate
percentage overflow. All four existing EMA stages, their seed, source handling,
warmup, and zero-denominator behavior are preserved.

Both versioned primary descriptions specify the interval [-1,1]:
[Pine v5](https://www.tradingview.com/pine-script-reference/v5/#fun_ta.tsi) and
[Pine v6](https://www.tradingview.com/pine-script-reference/v6/#fun_ta.tsi).
The preserved source/translation review has SHA256
`039ed0a6f24b35ecd249598a0bf3e26a9b446f6922dd99d8a7afb8eae46f1a89`.
The range fixture was frozen before implementation with SHA256
`5a76aacd6df1b88faf414b2a6bba389b0f859234b2c2e6f2748dea13357ef420`.
Its 16 version cases and all 90 events remain present. Finite-output range
checks are separate from complete expected trajectories, which remain
UNVERIFIED, including first-defined timing and NA gaps. No complete DIRECT
assignment or full Stage 2 acceptance follows from this block.

## Closed local state

Modern slots use `ta.tsi.state.v2` and the required literal profile
`tsi_ratio_legacy_seed_v1`. That profile describes the retained implementation;
it does not certify the seed as complete Pine parity. Old modern v1 checkpoints
are rejected with a replay-original-input diagnostic because saved series,
history and request outputs can be in percentage units. No automatic schema
rename, output conversion or history rewrite is provided. Pine 1–4 retain v1.

The payload has exact kernel/profile, stable positive integer short/long lengths,
an optional finite float previous source, and either none or all four named
stage dictionaries. Stage presence requires previous source. Each stage is empty
or has a finite-float warmup list, optionally with a finite-float seed value.
Warmup length is 1..L; a seed requires exactly L elements. Absolute-stage values
are nonnegative. Extra fields, incorrect types, partial stage-field presence,
nonfinite values, a missing profile and owner/revision mismatches are rejected.
A committed seed cannot disappear from working state.

A full warmup without a seed is permitted: the existing `fsum` can throw after
appending its final warmup value. Paired stages can also differ after an error
between their updates. Real public calls demonstrate these states both in an
aborted attempt and when a native caller catches the error and commits. The
closed decoder accepts these local representations in all relevant contexts;
it does not assert simultaneous seeding or equal paired counts. This adds no
generic decoder relaxation and does not change existing validators.

Admission uses the existing shared scratch decoder for root state, actual
compiled request children, successful abort anchors, attempted witnesses and
post-abort state. All checks run before live replacement. No provider or script
executes during restore. Ordinary checkpoint/transcript schemas, public ABI,
manifest, capabilities and source catalog remain unchanged. Exact host stack
identity also prevents cross-source checkpoint admission.

## Resource policy and verification

For modern TSI both lengths are bounded by the existing
`resource.max_collection_elements` before slot creation or mutation; restore
applies the same bound. This is an explicit runtime resource policy, not a Pine
syntax limit. No list is truncated or silently evicted. Existing aggregate
checkpoint, child and pending-witness budgets remain enforced. Earlier versions
retain their previous length behavior.

The frozen before fixture (SHA256
`382242c74460d4849383b3cbaf5fce5438427b1e71d50e1730b104c536a808cd`)
contains 56 genuine old checkpoints, 36 failure/resource observations and every
range event, recorded before source edits on both interpreters. These historical
outputs establish compatibility controls, not new Pine expected values. Tests
preserve finite-input subtraction overflow, partial signed/absolute fsum errors,
caught-error commit, abort/restore, old percentage overflow and resource failure.
The implementation keeps in-place updates and adds no complete-state clone.

Other tests exercise historical/realtime/deferred-fill routes, exact callback
retry, full/compact JSON continuation, late invalid children, all pending proof
locations, zero seeds, legacy admission, closed-shape negatives and resource
boundaries. Existing EMA/MACD, RMA, KC/KCW validators and semantic owners are
unchanged. TSI simple-int source metadata and complete seed/NA authority remain
separate work.
