# Stage 4 Request Engine architecture

## Contract boundary

`RequestEngine` accepts only typed `RequestQuery` values and immutable `DataSnapshot` results supplied by an admitted `RequestDataProvider`. The provider exposes a frozen `ProviderDescriptor` containing its canonical ID, schema ID, capabilities, and per-query bar ceiling. Runtime behavior never depends on a provider's Python class/module name or a reflected call signature.

`CanonicalBar` requires explicit UTC millisecond open/close boundaries, decimal-string OHLCV values, finality, revision, instrument/timeframe identity, and session identity. Missing `time_close`, unknown finality, non-canonical decimals, conflicting revisions, or context mismatch fail before expression evaluation.

## Dataset identity and lineage

A `RequestDatasetKey` binds query semantics, expression/call-site identity, result shape, provider and snapshot identity, revision policy, Pine version, gaps/lookahead, currency, and calculation limits. The registry stores immutable datasets by key hash and maps a separate discovery hash to the admitted dataset. APPEND snapshots reference the exact parent snapshot and lineage; only the appended delta is evaluated.

## Transactions and checkpoint

The registry maintains committed and working datasets, discovery mappings, and merge cursors. Each runtime callback begins a request transaction. Provider/evaluation/cache mutations are committed only with the callback; an exception or callback abort restores the prior registry byte-for-byte. Savepoints also make a failed nested request atomic.

Checkpoint payloads contain portable dataset keys, sealed evaluated values, child state, discovery mappings, and cursors. Provider objects and callables are never serialized. Restore validates provider identity and builds a replacement registry before swapping it into the runtime.

## Historical, realtime, and dynamic contexts

Historical callbacks discover request contexts. Realtime callbacks may only reuse already committed discoveries and never refetch an unseen context. A developing value is exposed only from an admitted developing snapshot and only when the request policy allows it.

Dynamic requests are determined by the immutable runtime policy and Pine version. Under the local policy model, v5 requires explicit enablement while v6's version default is enabled. Nested requests additionally require both runtime policy and provider capability and carry the exact parent child-context hash.

## Alignment

HTF alignment has separate paths for the four `gaps`/`lookahead` combinations. Historical selection never treats a developing bar as finalized. Realtime selection can read an admitted developing bar without contaminating the historical final path. LTF alignment returns only ordered intrabars fully contained by the chart bar and enforces the admitted intrabar limit.

## Exact ABI

Generated code calls `pinelib.abi.request.security_v1` or `pinelib.abi.request.security_lower_tf_v1` directly. The latter creates a real reference-heap array handle. Other request families are explicit fail-closed manifest rows rather than a generic `request.* -> na` fallback.
