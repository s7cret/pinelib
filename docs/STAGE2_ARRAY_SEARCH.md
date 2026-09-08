# Numeric array boundary searches

Pine 5/6 `array.binary_search_leftmost` and
`array.binary_search_rightmost` now return the documented neighboring index when
an ascending numeric array does not contain the query. Exact matches still select
the first or last duplicate, respectively. The implementation reuses the existing
binary-search loops in the reference owner.

The independent fixture was authored before runtime changes. It contains 24
cases and 48 indices, covering interior gaps, duplicates, first/last matches,
outer boundaries, singleton arrays, negative numbers and fractional values.
Both versioned references give `[-2,0,1,5,9]` queried with `3` as leftmost index
`2` and rightmost index `3`. The corresponding duplicate examples use
`[4,5,5,5]` queried with `5`, yielding indices `1` and `3`.
[Pine v5 reference](https://www.tradingview.com/pine-script-reference/v5/#fun_array.binary_search_leftmost),
[Pine v6 reference](https://www.tradingview.com/pine-script-reference/v6/#fun_array.binary_search_rightmost).

The absent-result correction applies to declared `array<int>` or `array<float>`
handles and exact finite numeric queries in Pine 5/6. It does not introduce a
full-array eligibility scan. The verified profile is finite, nonempty, ascending
numeric data; mixed, missing and unsorted payload outcomes are not newly claimed.
The existing comparison error guards remain in place. Empty arrays retain their
previous result, and native Pine 1–4 behavior is unchanged. The fixture explicitly
labels the v5 below-first leftmost boundary as an inference from the v6 reference.

The owner remains read-only: it changes neither the heap nor aliases, copies,
slices, checkpoint state or transcript state. Tests exercise historical execution,
realtime trials, repeated abort/retry, final commit, and JSON full/compact restore.
A counting sequence at the public detached-payload boundary confirms logarithmic
search element access for 65,536 values. This is a comparison/access bound, not a
claim that the preexisting whole-payload materialization is logarithmic.

There is no ABI signature, manifest, capability, heap schema or checkpoint revision
change. Ordinary `array.binary_search`, concat, sorting and matrix operations are
outside this correction. The existing v4 catalog availability and v6 optional
`sort_field` binding remain separately recorded gaps; this change does not hide
them or claim complete collection support, a TradingView export oracle, or Stage
2 acceptance.
