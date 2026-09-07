# Stage 2: typed reference values and reproducible library profiles

This source combines the preserved reference-values candidate and the archived locked-import work.
The existing heap, typed series, transaction slots and artifact identities remain the owners; there
is no alternate interpreter or broker. Arrays, maps and matrices with primitive element types have
fresh IDs per creation, shared aliases on assignment and independent written function contexts.
History stores references, not copies of payloads. `var`/`varip` retain different rollback policies;
JSON checkpoint restore checks cross-segment type and ID consistency before replacement.
Array iteration uses live size and element access with a resource limit, and tuple elements have
typed histories. The parser resolves receiver types from named bindings, preserves concat return
identity, and rejects direct global reassignment from functions while allowing content mutation.

Locked library linking retains exact `same_version_scalar_v1` reproducibility. New linking uses
`same_version_reference_v2`, permitting typed primitive-element array/matrix/map parameters and
array iteration. Library language versions still must match the consumer (5 or 6). The profile is
part of the dependency receipt, so changing the admitted subset changes identity explicitly.

Full Stage 2 is NOT accepted by the presence of this code. Exported UDTs/enums, overloads,
general generic functions, all loop-value forms, independent conformance of the complete builtin
surface and full once fill-recalculation remain separate unresolved criteria. Map/matrix for-in,
nested reference elements and mixed-language library imports are not newly admitted here.
Required protected-worker and two-interpreter verification is recorded separately by the host.
No local run, materialization job or test count is a TradingView execution oracle.
