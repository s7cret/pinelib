# Stage 2 nominal runtime candidate

This block adds generated-code services over the existing heap, slots and series.
It does not accept Stage 2 or claim external TradingView verification.

The exact `compiled_nominal_types` manifest advertises `compiler.nominal_types.v1`.
UDT and enum descriptors contain the source identity and declaration identity;
the runtime treats the descriptor tail as opaque and compares it exactly.

UDT construction admits an explicit field schema. Reads preserve nested reference
handles and enum values; writes validate the declared scalar or nominal type
before changing the heap. Copies have a new object identity and share referenced
children. Each copy retains its declared field rollback policy.

A `varip` UDT binding keeps the object identity. Only fields explicitly declared
`varip` preserve their changes between callbacks. An ordinary field returns to its
committed value (or its construction value for a retained new object). Nested
references remain valid, with their own rollback policy. This block admits
fundamental and enum `varip` fields; reference-valued `varip` UDT fields and varip
collections of UDTs still require the recursive admission contract.

Enums use exact nominal identities in bindings, field values, history and portable
checkpoints. Equality rejects a different enum type. Missing-history comparisons
return `na` in v5 and `false` in v6. Checkpoint restoration validates nominal field,
series and slot values before replacing the live session.

The `once` completion slot remains ordinary transactional state. The added tests
exercise actual `ORDER_FILL_RECALC` callbacks with deferred bar commits, lexical
calls, loop visits, abort and checkpoint/resume. Provisional historical callbacks
can roll back just as realtime callbacks do. Completion becomes permanent at the
bar publication boundary. This follows the documented ordinary `var bool`
equivalent; a completion-slot conversion to `varip` would change that behavior.

Independent expected values are hand-written assignments and counters based on:

- https://www.tradingview.com/pine-script-docs/language/objects/
- https://www.tradingview.com/pine-script-docs/language/type-system/
- https://www.tradingview.com/pine-script-docs/v5/language/operators/
- https://www.tradingview.com/pine-script-docs/language/conditional-structures/
- https://www.tradingview.com/pine-script-docs/language/execution-model/

These are engineering fixtures, not exported TradingView traces. Exact historical
broker scheduling remains a host/broker conformance criterion.

Performance was not measured in this block.
