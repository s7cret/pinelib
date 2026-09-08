# Rolling statistics: bar windows and current-call estimates

Pine 5/6 `ta.highest` and `ta.lowest` now preserve NA positions in their input
history. Their length counts bar observations; only the comparison excludes
NA values. Range, median, mode, variance and stdev continue counting valid
samples. The distinction comes from the versioned reference's function-specific
NA rules, not from a common Python rolling-window helper.

The current [execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/#time-series)
documents a full-window warmup for `highest`. The independent engineering
corpus labels the corresponding v5 and lowest warmup as inferred parity, rather
than a TradingView server observation. Mode resolves equal frequencies to the
smallest value. Even-window median and integer overload behavior are not newly
claimed by this change.

## Extrema checkpoint migration

Modern highest/lowest slots use `ta.highest.state.v2` and
`ta.lowest.state.v2`. Their payload has exactly `kernel` and `bars` fields.
The chronological `bars` list contains normalized finite floats and canonical
Pine NA. Slot owner, schema, kernel identity, persistence and both committed and
working payloads are validated before root or child checkpoint admission.
Pending-abort anchors, attempts and poststates use the same scratch decoder.
The extrema schema families are reserved across all revisions: an unknown
revision cannot bypass admission by claiming an unrelated slot owner.

Version 1 extrema buffers discarded NA positions. There is no sound general
conversion from those buffers to a bar history. Restoring a Pine 5/6 checkpoint
containing such a slot fails with a diagnostic requiring replay of the original
input from the beginning. No history is silently reset, truncated or relabeled.
Unrelated old checkpoints remain supported. Native Pine 1–4 paths and the
highestbars/lowestbars kernels retain their previous schemas and behavior.

The existing `max_collection_elements` resource policy also bounds each new
retained TA history. An oversized requested length or append fails with
`PL_RESOURCE_LIMIT` before mutation; history is not evicted when length shrinks.
The same bound applies at restore, alongside existing aggregate checkpoint and
compiled-child byte limits. No new configuration field or outer checkpoint
schema revision is introduced.

## Variance and standard deviation

The exact source signature includes optional `biased: series bool`, defaulting
to true, for both Pine 5 and 6. The current call selects the population divisor
N or sample divisor N-1. Changing this bool does not reset or reject the valid
sample history. Existing v1 estimate checkpoints preserve their initial-mode
metadata, without treating it as a constraint on later calls.

The ABI requires an exact bool and rejects other values before state access.
Pine 5 missing-bool parameter behavior remains unverified; this ABI boundary is
not a claim that Pine disallows every missing-bool expression. Admitted
language-level conversions belong to the producer/compiler, not Python
truthiness in the numeric kernel.

## Evidence boundary

The independent corpus contains 66 immutable cases for both versions, covering
finite/sparse/all-NA/unit windows, odd median, mode ties and both estimate modes.
Its expected results were authored before execution; a separate review checked
304 events using pairwise rational variance and high-precision square roots.
Owner tests add strict checkpoint corruption, genuine legacy captures, state
isolation, limits, realtime trial/abort/retry, full/compact continuation, and
actual compiled-request children without provider evaluation during restore.

This is a bounded Stage 2 correction. It adds no host evaluator, general TA
state migration, external TradingView execution oracle, or Stage 2 acceptance.
