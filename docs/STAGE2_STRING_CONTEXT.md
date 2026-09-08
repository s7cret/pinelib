# Versioned string value policy

The existing `pinelib.builtins.string` owner now accepts an optional admitted
`RuntimeLanguageContext` for `lower`, `upper`, `trim`, and `tonumber`. No new
string semantic owner or version resolver is introduced. Context-free calls and
the existing public `_v1` adapters retain their prior behavior.

New `_v2(tx, source)` adapters validate the active transaction and pass its exact
`tx.session.language` context. The four existing modern target rows point to
these adapters. Their source identities, supported versions `[5, 6]`, parameter
contracts, capabilities, pure effect and availability are retained. The normal
manifest generator adds the existing `RUNTIME_TRANSACTION` injection and moves
the source ABI parameter to position 1. Historical `tonumber` keeps `_v1`.

## Independently documented behavior

The [current Strings manual](https://www.tradingview.com/pine-script-docs/concepts/strings/)
defines case conversion for ASCII letters, boundary trimming for ASCII
whitespaces, and numeric conversion from ASCII decimal notation with an optional
leading sign. The v6 owner preserves non-ASCII letters/whitespace and admits the
entire decimal input before the existing float conversion. Scientific notation,
Unicode digits, underscores and surrounding spaces produce canonical NA. The
decimal matcher uses `fullmatch`, so a trailing newline is not accidentally
accepted by an end-of-line anchor.

The [v5 trim reference](https://www.tradingview.com/pine-script-reference/v5/#fun_str.trim)
and current v6 reference both specify an empty result for an NA source. Explicit
v5/v6 context enables this rule for `trim`; other missing-value/type policies and
the original context-free adapters are retained. Frozen reference payloads
`91998.b1f3e2c03b5a108b7bd6.js` (v5) and
`42609.02dff4dd64cef27aa3f4.js` (v6) both bind this remark to translation 162284 in
`en.21857.4889c7a70444e16ac9c7.js`.

V5 does not have the current manual's detailed Unicode/decimal restrictions.
Its previous runtime behavior remains a compatibility control. Three numeric
expectations in the original v5 table remain explicitly **UNVERIFIED**; they
have not been rewritten or claimed as corrected Pine behavior.

## Frozen expectations and checks

The unchanged original table, `tests/fixtures/string_manual_expected.json`, has
34 examples and 63 version observations. Its SHA256 is
`67362aaa9d69bdb9297fbf862a870f4218cfef8493602936f2dca4522df728ac`.
Before this change it produced eight documented v6 differences and three v5
inference differences. Afterward all 34 v6 cases and 26 common v5 controls match;
the three v5 inference differences remain visible in separate reports.

The separately authored `string_context_supplement.json`, SHA256
`7163768f5dacd31dc66a99971d7c9a60e535a1cafddd96c2213c8228c5a020f0`,
was frozen before new semantic execution. It contains two versioned NA trim
expectations, 18 extra ASCII/decimal boundaries and eight explicit native legacy
controls. Neither table is a TradingView export. Overflow/underflow, numeric
midpoint conversion, non-BMP length and the complete string family remain
outside the proof.

All 283 new tests pass on Python 3.11 and 3.13. They exercise direct owner and
target ABI calls, strict native types, default/v1–v5 compatibility, closed/stale
transactions, full-input decimal boundaries, and real historical/realtime
trial/abort/retry/full-compact checkpoint behavior. Before the adapters/context
API existed, the same new suite had 248 failures and 35 passes on the exact
`d33fdea2ff3d2fa3c567c2c83da08664c8937fc1` baseline. Those API-admission failures
are distinct from the original semantic differences.

The complete 2296-test runtime inventory has 2291 passes and five failures on
each interpreter: three preexisting Windows release-tool cases and two old
whole-manifest identity checks. The two identity fixtures need a separately
reviewed metadata-only migration derived from the frozen baseline plus the four
declared row changes. Their original assertions and failure evidence are
preserved; this functional change does not update them.

There are four production files, one new test, two frozen fixtures and this
document. The manifest schema and capability denominator do not change. Source
language admission, generated host corpus and coordinated Linux validation are
separate requirements. Full Stage2 acceptance remains false.
