# obj_only

Eight sealed object refinements build canonical rational polynomials, Bernstein
sign certificates and complete root atlases. The only invention permission is
`object`; operations, combinators and observations are closed at the library
boundary. All certificate constructors recheck public coefficients, witnesses,
and contiguous partitions with exact rational arithmetic; no floating point or
stored acceptance flag is used.

Layer zero includes exact integer/list primitives, five fixed finite-list
combinators, generic `make_record`/`field`/`tag`/`field_count` record operations,
generic `rat_parse`/`rat_format` for exact rational spellings, generic
exact pair arithmetic (`rat_add`/`rat_mul`/`rat_div`/`rat_pow`/`rat_lt`/`rat_eq`), and
`value`/`accepted` probes. These primitives never decide a certificate's validity.
Normalization, Bernstein bounds and certificate checks are kernel-node
expressions whose generic arithmetic calls are metered. Parsing and formatting cache
results without changing the charged primitive calls. A bounded subdivision
exhaustion uses `bounded_count(-1)` to return `Unknown(resource)` rather than
a false sign claim.

Regenerate the export with `python -m opulse.worlds_v2.obj_only.export` and run
`pytest tests/worlds_v2/obj_only`.
