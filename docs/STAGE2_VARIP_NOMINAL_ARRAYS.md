# Varip arrays of admitted UDTs

The generated target now supports Pine 5/6 `varip array<UDT>` when the admitted
UDT contains fundamental fields, optionally declared `varip`, and ordinary
fields containing fundamental arrays or matrices. Empty arrays and typed `na`
bindings are checked against the immutable registry before an initializer runs.
No constructor execution or checkpoint-supplied schema establishes eligibility.

The profile is grounded in the archived
[v5 Arrays manual](https://www.tradingview.com/pine-script-docs/v5/language/arrays/#using-var-and-varip-keywords)
and current [Arrays manual](https://www.tradingview.com/pine-script-docs/language/arrays/#using-var-and-varip-keywords).
The [Objects manual](https://www.tradingview.com/pine-script-docs/language/objects/#creating-objects)
distinguishes a persistent object reference from persistent fields. The original
read-only matrix preserved 20 runtime and 10 compiler failures for the five
documented schemas across Pine 5/6.

## Persistence and aliases

The explicit array and its slice backing retain their element lists across
intrabar rollback. Reachable UDTs retain identity, while ordinary fields reset
and declared `varip` fields persist. Ordinary primitive field collections retain
identity and follow their own rollback policy; an explicit varip binding of the
same collection changes the policy for all its aliases. Insertion into the outer
array does not globally promote every reachable object.

New UDTs may be inserted after the root binding exists. Retention follows both
constructor/committed and working reference edges, so an ordinary field that was
reassigned during an attempt can return to its constructor baseline safely. A
subsequent rollback can collect temporary objects that are no longer reachable.
Array and UDT copies preserve shallow referent aliases without copying the
source container's explicit persistence policy.

Graph validation checks existing nominal owners and fundamental payload owners
before promoting a root or publishing a mutation. Mutations through ordinary
field aliases are checked while reachable from an admitted persistent nominal
array. Failures leave payloads, flags and revisions unchanged. An internal
derived root index avoids scanning unrelated heap objects when no such array
exists; it is reconstructed from admitted heap metadata and is not serialized.

Slice bound checks remain in their established owners. A legal backing shrink
can temporarily invalidate a view until rollback repairs it; typed graph checks
do not turn that transient state into a general checkpoint exception.

## Target and checkpoint contracts

The additive closed manifest property `compiled_varip_nominal_arrays` advertises
`compiler.varip_nominal_arrays.v1`. It requires the existing nominal-registry and
varip-reference capabilities. The prior `compiled_varip_reference_storage`
revision 1, fundamental array/matrix/map behavior, and official callable rows are
unchanged. The compiler records the new requirement in the lowering plan and
generated artifact, including inferred, empty and missing array declarations.
The compiler does not import the runtime declaration owner.

Existing reference binding APIs, opaque nominal IDs, UDT schema fields and
`intrabar_persistence` checkpoint fields are sufficient. No checkpoint format
revision is added by this array feature. Retained aborts use the separately
defined ordered abort witnesses, replaying the same heap owner; full/compact
transcript controls and retry sequences retain their existing behavior.
Request child admission inherits the same registry and validates the array graph
before replacing parent state, without fetching data or executing callbacks.

## Verification boundary

Tests exercise owner APIs and actual generated code, both Pine versions,
full/compact checkpoints, historical fill callbacks, realtime trials, aborts and
same-sequence retry, fresh object reachability, ordinary/explicit-varip aliases,
copies/slices, invalid types and schemas, atomic resource rejection, and nested
request checkpoint tampering. The preceding abort/control regression suite is
retained unchanged.

This bounded profile does not enable enum elements, enum-valued UDT fields,
UDT-to-UDT fields, arbitrary recursive collections, map-valued fields, or
reference-valued varip fields. Those are separate admission/execution questions;
the restriction is not a claim that Pine forbids every deferred shape. It adds
no host semantics and does not constitute completion of Stage 2 or an external
TradingView execution-oracle claim.
