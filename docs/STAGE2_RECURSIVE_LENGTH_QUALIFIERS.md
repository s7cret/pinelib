# Modern TSI target length qualifiers

The existing `ta.tsi` target row now specifies at most `simple int` for `short_length` and `long_length` in Pine v5/v6, matching the two official version-specific references. Only those two qualifier fields and the derived manifest content hash change. Its 1107 other rows remain identical. MACD already had the correct target metadata and is untouched here.

The producer companion separately corrects three MACD and two TSI length qualifiers through its existing override owner. All v1–4 producer pack bytes remain identical. No runtime kernel, callable, ABI order/mapping, availability, capability, manifest schema, state, checkpoint, EMA seed, or TSI scale behavior changes in this metadata wave.

The literal target expectation was frozen before the builder ran (SHA256 `d23e25b0f3bad9e4702ca47ca116dafaacdd4cb205ecbcd1ce92e36a1b269559`). Independent construction from the prior manifest plus these two qualifier changes produces content hash `sha256:3bbb194318736ff97aff6a50ef4a3c4238fda3191f3971ab2e5fe9e14e27c2f7`. New tests check the exact row, version profile, all remaining fields, original ABI signature, and rejection of inferred overlays for other names/categories.

Whole-manifest fixture identities necessarily change. A separately reviewed ten-file fixture migration changes only aggregate metadata hashes and corresponding literal file checksums in existing runtime and producer tests. Numeric values, original test logic, source authority/provenance, and legacy pack evidence remain unchanged. The production/new-test publication groups exclude that migration.

Normal-source verification uses the original independently authored 30-case manual, retained before observations, and 60 positional/named cases. Both Python versions admit and compile all 40 const/input positives and reject all 20 series negatives at the producer. This is an admission check without numerical runtime execution, a TradingView execution oracle, or new DIRECT expected assignments.

The compiler normalizes target source parameters to names and ABI bindings, dropping qualifier ceilings. Normal-source enforcement in this wave comes from corrected producer facts; general compiler certification of source/target qualifier compatibility remains unresolved. Compiler files are unchanged.

Verification runs against an explicitly indexed composition of the existing occurrence companion on runtime base `2148bca8370858ef8f7716ee0ba27d42960563b4`, producer base `05d7e61be58a184b211bc093f989527157005b92`, and unchanged compiler `95a14be4be8987faafb3e7629c744e698fd9f134`. It is not a published-final-pin claim. Full Stage2 acceptance and coordinated Linux acceptance are not asserted.
