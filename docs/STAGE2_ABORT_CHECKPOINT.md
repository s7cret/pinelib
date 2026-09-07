# Retained abort checkpoints and bound callback control

This bounded Stage 2 change repairs a preexisting native-runtime inconsistency:
an aborted realtime attempt retained `varip` values, but its checkpoint could not
be restored because the successful transcript still described the preceding
successful callback. The defect was independently reproduced on published
`c90c267` and the immutable nominal-registry candidate `2a5dce3`.

An ordinary abort does not consume its callback sequence or append a successful
transcript entry. A UDT's ordinary fields roll back; its declared `varip` fields
remain retained. A same-sequence retry observes those retained values. For the
independent counter fixture the trace is `[ordinary, varip]`: historical commit
`[0,0]`, successful realtime trial `[1,1]`, abort `[0,2]`, final retry `[1,3]`.

## Successful control and format compatibility

| Native format | Legacy version | Additive version |
| --- | --- | --- |
| `openpine.runtime_transcript.v1` (full) | `1.0.0` | `1.1.0` |
| `openpine.runtime_transcript.v2` (compact) | `2.0.0` | `2.1.0` |
| `openpine.runtime_checkpoint.v1` | `1.0.0` | `1.1.0` |

Every new successful transcript entry contains the closed field:

```json
"control": {"bar_commit_mode": "deferred", "boundary": "callback"}
```

`bar_commit_mode` is exactly `callback` or `deferred`. `boundary` is exactly
`callback` or `bar_commit`. The mode comes from the established session mode;
the publication boundary comes from the actual `finalize_bar` operation.
An arbitrary callback phase named `BAR_COMMIT` remains a callback. A publication
must immediately follow its confirmed provisional callback, with matching
coordinates and the next sequence.

Existing entry dictionaries remain an unchanged prefix. The first new entry
after a legacy checkpoint uses that checkpoint owner's admitted mode. A modern
control entry cannot be followed by a legacy entry or a different mode. Entry
control is included in the existing full transcript hash or compact append-only
chain; the state hash algorithms remain unchanged. An old checkpoint round-trips
unchanged until a new successful callback or retained abort requires the new
profile. No legacy transcript is rewritten to describe an abort.

Checkpoint version `1.1.0` is required for a modern transcript or a pending abort.
Its ordinary runtime fields remain closed; `pending_abort` is optional but cannot
be null. Version `1.0.0` forbids both new features. `RuntimeCheckpoint.seal` selects
the exact version from these owner-defined features when its version argument is
omitted. Explicit mismatched versions are rejected by runtime admission.

## Ordered abort evidence

`pending_abort` is a closed object with:

- `schema_id`: `pinelib.pending_abort.v1`.
- `transcript_hash`: the unchanged successful transcript digest.
- `state_hash_algorithm`: the existing full snapshot or compact semantic scheme.
- `state_hash`: the actual post-abort runtime-state digest.
- `successful_state`: the ordinary runtime segments at the last successful
  callback, excluding transcript and pending evidence.
- `attempts`: a nonempty ordered array of `{frame, attempted_state, new_series}`.
  The frame has every `CallbackFrame` field; attempted state has exactly the
  ordinary runtime segments; new series IDs are sorted and unique.

The successful-state evidence is admitted by the ordinary checkpoint owner and
must match the unchanged successful transcript's terminal digest. Empty success
history requires an exact empty initial state. Each attempt sequence is greater
than the last successful sequence; native sequence gaps and same-sequence retry
remain supported. The attempt's mode is bound to successful control. The first
attempt after a provisional success must use that provisional bar.

Replay occurs entirely on scratch owners. The real begin projection is applied
to the preceding state; the attempted state is decoded with the same declaration
and nominal owners. Surviving declarations and all committed baselines must be
unchanged. New allocations and slots are uncommitted; `new_series` must equal the
actual set difference of attempted and prior series IDs. The actual abort
projection then removes ordinary new declarations, retains explicit typed
`varip` declaration metadata, and performs the existing segment rollbacks. The
result becomes the next witness's baseline. Every final segment must equal the
checkpoint's strict, normalized post-abort state before any live replacement.

This ordered representation preserves one-pass heap retention: a temporary
reference may survive one rollback through a pre-rollback ordinary UDT field and
be collected on a subsequent attempt. It does not assume a second rollback is
idempotent and does not loosen committed-history or ordinary-field checks.

Committed request state is identical throughout the witnesses. Its exact child
checkpoint graph is validated once by the existing bounded child traversal;
equivalent witness copies do not count the same dataset repeatedly. Replay never
executes generated code, request evaluators or provider fetches.

## Temporary slice bounds

A legal backing-array shrink can temporarily invalidate an existing slice; an
access raises a bounds error and an ordinary abort restores the backing. A newly
allocated slice after a grow can also exceed the parent's committed length until
the allocation is rolled back. Those pre-abort states are necessary witnesses.

Only the private heap witness decoder defers the **upper bound against backing
length** for working slices and initial descriptors of uncommitted new slices.
Marker shape, integer/nonnegative/ordered bounds, parent identity and kind,
matching element type, graph cycles, nominal membership, and globally committed
slice bounds remain strict. Existing backing values are still type-checked and
every typed backing node is validated independently. The temporary flag is
cleared before the heap is returned. Public heap/checkpoint decoding and ordinary
slice reads remain strict. An invalid view surviving the final rollback is
rejected before replacement.

## Resource failure and lifecycle boundaries

The existing `max_checkpoint_bytes` budget also bounds live witness growth.
Appending an attempt counts its canonical UTF-8 bytes and separators exactly;
previous witnesses are not serialized again. The complete outer envelope,
successful evidence, current state and transcript are included in the budget.
Restore uses the same aggregate input byte/node/depth limits, including nested
request checkpoints and all witnesses.

If an attempted abort would exceed that budget, the transaction is rejected with
`PL_RESOURCE_LIMIT`. It restores the exact preattempt values, owners, caches,
control, sequence and previous valid pending proof. This is a rejected transaction,
not a successfully completed ordinary abort. No new reference is leaked and no
unrecorded retained state is published. A retry or publication of the preceding
provisional success remains possible. The successful compact path still avoids
serializing growing committed histories.

A proof is emitted only for a retained data change, an existing pending proof, or
an actual control change (establishing deferred mode or clearing a provisional
frame). A no-effect abort at an already established publication boundary remains
byte-identical. An initial no-effect nondeferred abort also rolls back its transient
mode, preserving live/restored equivalence. A successful callback clears the proof;
successful provisional state still requires explicit bar publication before export.

The OpenPine host retains its separate committed-bar receipt/export boundary and
must use the new explicit publication field when present. Native pending-abort
support does not authorize exporting an open host bar or a retained native abort
through that outer protocol.

## Verification scope

New owner tests cover Pine 5/6, full/compact state, first/repeated aborts, exact
retry traces, genuine legacy migration, mode/version and witness tampering,
ordinary/committed-state preservation, temporary slices, nested child admission,
exact resource boundaries and atomic resource rejection. Original failed
reproductions and independent after-results are retained separately under the
host's `.runtime/evidence` directory. Existing semantic assertions were preserved.

This is checkpoint consistency and a bounded lifecycle repair, not authentication
of arbitrary externally rewritten transcripts, a TradingView conformance claim,
recursive `array<UDT>` persistence, or acceptance of the entire Stage 2.
