# Stage 2 nominal registry admission

Generated nominal programs now supply their complete immutable declaration registry
when constructing `RuntimeSession(..., nominal_registry=registry)`. The runtime does
not learn enum members or UDT schemas from values, constructor calls or checkpoint
metadata. Nonnominal sessions may retain `None`; their existing identity input is
unchanged. Recursive varip persistence is not enabled by this change.

The compiler target advertises this exact additive contract:

```json
"compiled_nominal_registry": {
  "revision": 1,
  "schema_id": "pinelib.nominal_registry.v1",
  "identity": "source-declaration",
  "admission": "module-literal-before-execution",
  "min_pine_version": 5
}
```

The consumer capability is `compiler.nominal_registry.v1`. The registry hash uses
the existing canonical JSON SHA256 owner. The registry hash joins runtime identity
before requests are bound. Child request sessions and checkpoint candidates receive
the same admitted owner before restoring state. Registry payload/schema admission
belongs to `pinelib.reference.registry.NominalTypeRegistry.from_json`; the compiler
and host retain responsibility for verifying the generated artifact and matching its
source/version to that registry.

Registry declarations preserve exact source/declaration identities, ordered enum
members and titles, and UDT field types and varip flags. Forward and cyclic UDT type
references are representable; all referenced declarations must exist. Defensive
serialization, immutable nested records/indexes, byte/node/depth limits and a bounded
container-cycle check prevent mutable caller input from changing admitted proof.

Runtime construction, coercion, mutation, copying and restore check enum name/ordinal
pairs and exact UDT schema metadata against that registry. Typed arrays, matrices and
maps validate their nominal elements, including map keys. Erasing a container or
series type descriptor cannot make a UDT/enum value valid as a scalar. Slice validation
checks committed and working bounds and backing types in their respective phases.
Restore builds and validates candidate segments before replacing live state.

Parent restore also validates every reserved `compiled-runtime` checkpoint in its
request datasets before replacing any parent segment. A shared session factory
derives child identity from admitted snapshot-provider instrument/timeframe metadata
and the parent's language, policies, inputs and immutable registry. Restoring saved
children uses the ordinary runtime segment validators without fetching bars or
executing generated expressions. Unknown enum members in cached children therefore
fail at parent admission even when every nested checksum has been recomputed.

An explicit work list covers recursively saved children under cumulative dataset,
state-byte and cache-byte budgets. Request depth is zero-based: the first requested
child is depth zero. Portable input is checked for cycles, a transport depth of 128,
and the existing checkpoint byte limit before canonical decoding. Canonical `na`,
tuples and existing portable enum/reference values retain their original owner
conversion; malformed codec inputs raise a runtime error. Ordinary request state
under other keys is not interpreted as a runtime checkpoint.

These checks establish declared membership and internal type consistency. They do
not authenticate a checkpoint or prove that every otherwise valid value arose from
executing the source. Binding every serialized storage identity to a source variable
declaration is a separate contract.

## Independent evidence and verification

TradingView defines an enum's possible values through its declared members, and UDT
field declarations determine field behavior. [Enums](https://www.tradingview.com/pine-script-docs/language/enums/),
[Objects](https://www.tradingview.com/pine-script-docs/language/objects/).

`tests/test_nominal_registry_runtime.py` deliberately recomputes checkpoint and full
transcript hashes after corruption. Its assertions require rejection of undeclared
members, incorrect ordinals, altered UDT schemas/varip flags, foreign values in typed
containers, erased collection/series descriptors and malformed committed slices.
Positive cases preserve valid JSON round trips, cyclic reference identity, versioned
missing values and request-child compact checkpoint continuation. The existing
historical/realtime/rollback nominal tests retain their expected values.

`tests/test_nominal_registry_request_restore.py` adds 71 checks for parent admission
of actual compiled request children: full and compact checkpoints, recomputed enum
forgeries, metadata/identity changes, late child failure with unchanged live parent
segments, recursive count/byte/depth budgets, and live continuation with decoded
`na` history. The independent initial nested-child reproduction accepted the forged
parent checkpoint; the unchanged reproduction now rejects it on Python 3.11 and
3.13 without replacing live state.

Final local full suites each report 943 passed and three existing Windows packaging
failures out of 946 tests, with zero skips. The three failures concern deterministic
source archive timestamps, symlink support and executable file modes; their required
Linux verification remains separate from the local runtime results.

The isolated registry tests cover complete declaration closure, exact schema/version
admission, immutability and resource bounds. Their separate varip eligibility query
has the initial array-only profile with fundamental or fundamental array/matrix UDT
fields; it is not connected to runtime persistence. This bounded profile follows
[v5 Arrays](https://www.tradingview.com/pine-script-docs/v5/language/arrays/#using-var-and-varip-keywords).
Wider map/matrix and recursive persistence require their own execution fixtures.

Existing nominal fixtures now supply explicit admitted registries. Previously
conflated parent/child field schemas use separate declaration IDs; the Point/Side
declaration node IDs and all behavioral assertions remain. This is test setup
migration, not a change to expected Pine results.

This change does not mark Stage 2 accepted.
