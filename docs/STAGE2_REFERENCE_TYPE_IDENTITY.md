# Reference type identity — constructor/host parity

A real cross-layer regression was exposed by the new numeric corpus: finite
`array.binary_search_leftmost/rightmost` calls on v5 native `array.new_float`
returned -1 for interior gaps, although the same data allocated by a host using
`array<float>` returned the documented neighboring index.

The heap intentionally retains both representations in existing checkpoints:
native constructors pass an element descriptor; host/request allocations may
pass the whole collection type. Neither format is a newly inferred payload type.

`RuntimeReferenceHeap.normalized_type_descriptor` is now the single comparison
view for these descriptors. Search eligibility, typed variable admission and
nominal reference-field admission use this same view. Raw `type_descriptor` and
checkpoint bytes are unchanged, as are nominal-registry and payload validators.
No generated-code special case or second search algorithm was introduced.

The frozen independent v5 examples are backed by the reference manual's interior
missing-neighbor and duplicate examples. They run through the native compiler
as well as direct ABI calls. Root tests additionally cover both descriptor
representations, int/float, aliases/copy/slice, abort, full/compact checkpoint,
and invalid handles. Prior v1-v4 native policy and nonnumeric cases are preserved;
this fix makes no claim about v4 binary-search language availability.

Reference: https://www.tradingview.com/pine-script-reference/v5/#fun_array.binary_search_leftmost
