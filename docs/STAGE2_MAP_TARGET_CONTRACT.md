# Stage 2: map put and put_all target contracts

This change corrects four projected target rows: namespace and method forms of
`map.put` and `map.put_all`, each available in Pine v5 and v6. The existing
runtime ABI functions and map implementation are unchanged. No availability,
capability, schema, catalog identity or frozen source-inventory row is added or
rewritten.

Both reference versions define `map.put(id, key, value)` as returning the previous
value for the key, or `na` for a new key. The projected Pine return type is now
`V`, matching the existing ABI runtime type. The two source argument types are
`K` and `V`, corresponding to the map's declared key and value types; the opaque
map receiver type is unchanged. This removes the old false `string` key
restriction in these two rows only.

Both versions define `map.put_all(id, id2)` with a void result. Its second source
parameter is now `id2` in namespace and method forms. A correction scoped to this
exact callable name and callable category binds `id2` to the existing ABI
parameter `from_handle`. Method receiver injection continues to use the existing
owner. This is not a global alias for arbitrary `id2` parameters.

Primary references:

- [Pine v5 map.put](https://www.tradingview.com/pine-script-reference/v5/#fun_map.put)
- [Pine v5 map.put_all](https://www.tradingview.com/pine-script-reference/v5/#fun_map.put_all)
- [Pine v6 map.put](https://www.tradingview.com/pine-script-reference/v6/#fun_map.put)
- [Pine v6 map.put_all](https://www.tradingview.com/pine-script-reference/v6/#fun_map.put_all)
- [Pine v6 map type templates](https://www.tradingview.com/pine-script-docs/language/maps/)

The independently reviewed primary extraction receipt has SHA-256
`d299bd8eee900afcf9a991cb911c028960bc47e286f831bd6c252e8e4a6d159a`.
Its v5 reference module has SHA-256
`e52daf777c5e777855537812e57cff57123dd6b2568f98b00dc62d20fbc6bfb5`;
the v6 module has SHA-256
`64e0b95b73fd95b198a12feda5129a94840ff0ea5f857f26bfc068cc484bbebe`.

The expected four complete rows and the unchanged remainder hash were authored
from the frozen `d33fdea2ff3d2fa3c567c2c83da08664c8937fc1` manifest plus only
the literal metadata changes above, before running a modified builder. The
metadata fixture has SHA-256
`c3fdcfcff7c58e4e7b789d1e81e0309e1ef661df8fd2fc17859b4606cdf0b9d9`.
The normal `python -m pinelib.abi build` command produces the independently
predicted content hash
`sha256:0fa328ead6139c7f9813869fefe7b3ec3d0f0a2923faa64e0367fbfe26a59d77`.

The 68 new tests check exact four-row identity, v1-v4 exclusion, v5/v6 inclusion,
the complete unchanged manifest remainder, callable-only corrections and narrow
second-map binding. They also preserve the existing ABI signatures and execute
10 relevant rows from the separately authored 28-row map table in both versions,
checking typed previous values, canonical NA, void results, insertion order,
source preservation and self-copy behavior. That original table has SHA-256
`3afd6e3a0a1a0abe972c40190bff3dd2caf566aa5e7a7a355aa9d2acd5bb9ffe`.
Neither expected values nor metadata expectations come from the modified runtime.
The original 27 failing metadata checks are retained as before evidence.

Existing whole-manifest remainder hashes in the concat and min/max tests require
a separately reviewed metadata identity migration. Their assertions and fixtures
are unchanged in this bundle; their expected failures must remain visible until
that migration is applied. The runtime kernel, ABI callables and all old tests
retain their original bytes.

The stale key metadata of neighboring `map.get`, `map.remove` and `map.contains`
rows is a separate residual issue. This change does not certify those contracts,
NA keys, missing bool-valued lookup rules, reference-valued shallow copies, map
capacity limits or complete map conformance. Generated source integration and
formal host corpus evidence are separate work. Full Stage 2 remains in progress.
