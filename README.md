# PineLib 5.0.0rc6 — Stage 4 local implementation candidate

This source tree extends the Stage 3 direct runtime ABI with a canonical Request Engine. Request execution consumes immutable `openpine.marketdata.v2`-shaped snapshots through a strict provider protocol, binds every dataset to explicit semantic identity, and participates in the runtime transaction/checkpoint model.

## Implemented architecture

- Strict `RequestDataProvider` protocol with an immutable capability descriptor; runtime request execution does not inspect callable signatures or provider module names.
- Explicit `RequestQuery`, `CanonicalBar`, `DataCoverage`, and sealed `DataSnapshot` contracts. Exchange, market, provider identity, `time_close`, finality, revisions, coverage, and snapshot hashes are mandatory rather than inferred.
- Transactional `RequestDatasetRegistry` with discovery identities, immutable lineage, merge cursors, savepoints, rollback, resource ceilings, and portable checkpoint serialization.
- Historical discovery plus fail-closed realtime reuse: an unseen request context cannot first appear on a realtime callback.
- Version-bound dynamic request policy: v5 requires explicit enablement; v6 defaults to enabled unless disabled by the admitted policy.
- Isolated child expression state keyed by request/call-site context; nested requests are capability- and depth-bound.
- Separate HTF alignment algorithms for `gaps_on/off` and `lookahead_on/off`, with historical and developing realtime values kept distinct.
- `request.security_lower_tf` returns ordered intrabar values and the ABI facade materializes a deterministic Pine array handle.
- Scalar, tuple, array, UDT, and map result shapes are validated and restored without coercing the dataset to a float series.
- Only the exact invalid-symbol taxonomy may be masked by `ignore_invalid_symbol`; transport, schema, revision, coverage, and unavailable-dataset errors remain fail-closed.

## Local target surface

The bundled local catalog contains 275 classified rows:

- 266 direct supported rows, all imported and executed by the manifest-driven behavior test;
- 9 explicit `UNSUPPORTED_FAIL_CLOSED` rows (`math.random` and eight provider-dependent request families);
- `UNKNOWN=0` inside this local catalog.

This is not represented as the authoritative full Pine v1–v6 denominator. The exact Pine2AST RC6 version packs, contract-owned RC6 schemas, canonical provider wheel, and sealed TradingView request oracle exports were not included in the supplied packet.

## Validation performed

- full Stage 2–4 pytest regression suite;
- line and branch coverage with the configured 95% fail threshold;
- manifest drift, import, signature, and supported-row execution checks;
- provider contract, identity, revision, coverage, result-shape, HTF/LTF, dynamic/nested, realtime, rollback, checkpoint, and resource-limit tests;
- deterministic property/mutation/fault cases and incremental merge benchmark evidence;
- production architecture scan for reflection heuristics, implicit market defaults, close-time inference, generic dispatch, and broker-domain leakage;
- wheel/sdist double build, wheel RECORD verification, clean wheel-only install, and `pip check`.

The delivery's `IMPLEMENTATION_REPORT.md`, `TASK_STATUS.json`, and `FINAL_GATE.json` define the exact evidence and acceptance boundary. Merge, tag, release, and deployment are not authorized by this packet.
