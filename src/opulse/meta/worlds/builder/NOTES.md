# builder@1

`World<...>` values and the `builder@1` declaration use the finite-world
schema in atoms-meta section 6. Layer 0 provides card construction and access,
list operations, integer and text operations, finite-sort enumeration, `wf`,
`world_hash`, `size`, and metered `call_in`. Each rule's declaration digest is
the SHA-256 of its Python source. `call_in` charges one dispatch step plus the
inner layer-0 steps in the same trace; it does not charge on preflight failure.
An optional canonical list of statement code cards declares checked world laws.
The Z5 world states #add5_assoc and #mul5_distributes on all 125 triples each;
a changed table invalidates its law's referenced atom digest. Well-formedness
checks laws after bodies and before probes. The builder verifies corresponding
invented equations against the built table atoms through the core law pipeline;
one promoted associativity step is replayed on its exact checked scope. The
false #mul5_cancels is callable but unpromoted: (z0,z0,z1) is its counterexample.

The cross-world ~embed_z5 maps Z5 into the zero-bit slice of Z5xBool. Core
BridgeContext verifies add5/add_pair commuting on all 25 pairs. Separate exact
metered call_in tests dispatch through both built world values (two steps per call).
Zn[n] is a bounded family for n=3..7: a kernel-body generator constructs each
total modular-addition world; generators.instantiate_family verifies the template
and each ordinary instance in its own pipeline before promotion. Each instance
has its own world value, evidence and content-addressed dependency on Zn. The
template's family evidence records size 5; each instance records size 1.

| Definition | Kind / layer | Recorded verification scope |
|---|---|---|
| `base_z5` | object / 1 | 1 world with 75 binary rows and 5 unary rows |
| `add5_assoc` | law / 1 | all 125 Z5 triples, equation and rewrite evidence |
| `mul5_distributes` | law / 1 | all 125 Z5 triples, equation evidence |
| `embed_z5` | bridge / 1 | 5 source residues and all 25 add5/add_pair pairs |
| `hide` | operation / 1 | 2 one-probe worlds |
| `repair` | operation / 1 | 20 unary worlds, sizes 2 through 4, one missing row each |
| `product` | operation / 1 | 14 ordered pairs; enum, range, and bool sorts, unary and binary tables, up to 81 rows per product table |
| `count_row` | operation / 1 | 2 accumulator-row pairs |
| `for_each_tuple` | combinator / 1 | 1 four-row table with `f = count_row` |
| `table_total` | operation / 2 | 2 tables of 4 and 9 rows, `f = count_row` |
| `product_table_total` | operation / 3 | 1 pair of two-element unary worlds |
| `audit_product` | operation / 4 | 1 pair, checking the actual product's row count |
| `same_verdict` | operation / 2 | 3 worlds including an incomplete table |
| `audit_hidden_product` | operation / 5 | 1 pair, checking count and hidden-probe verdict |
| `Zn` | template / 2 | bounded family of 5 modular worlds, sizes 3 through 7 |
| `Zn_member_0` ... `Zn_member_4` | object / 3 | each member independently verified on its exact produced world |

All invented bodies are kernel nodes. Every member passes write, check,
sample, reference/unfold verification, account, and promote. The `product`
definition enumerates every input tuple through measured recursion, calls
both components, and constructs the resulting table row. The recorded pairs
have matching operation names, order, roles, arities and finite output sorts;
the definition does **not** claim a verified result for incompatible signatures,
error cells, unbounded `int`/`str` sorts or products exceeding the finite table limits.
Nor does the recorded product scope include components carrying declared laws.
`hide` filters every selected probe; `repair` fills the first missing unary row
in the first table using its declared `err(missing)` cell.

The derived tower starts with the given `add5` table. `times5` is measured
recursion over `rank` and agrees with the given `mul5` table on all 25 pairs.
The ledger promotes it and `extend` accepts that ledger directly. A second
measured recursion, `power5`, calls the promoted multiplication body; its
results and unfolding agree on all 25 pairs with the independent `pow5` table.
For inputs `(z3,z2)`, `mul5` costs 1 layer-0 step, `times5` costs 7,
the given `pow5` table costs 1, and derived `power5` costs 25. Changing
one input table cell changes the hash; the original ledger cannot extend the
changed world.

The showcase checks a four-sort, four-operation world whose observation
reaches an act table through two body operations. Invert exhausts 3125
assignments to the last row of `mul5`. Compute counts the accepted associative
worlds among 2187 three-state table assignments with a body probe. The ladder
gives concrete sizes and dependencies at five levels. The export is rebuilt
with `python -m opulse.meta.worlds.builder.export`.

Local adapter: `BuilderLibrary` uses the metered evaluator because core
`Library` has no evaluator hook. It filters polymorphic card-primitive
argument-sort false positives from the core checker; all other checks remain.
The stock `Ledger` now supplies `promoted`; no ledger adapter is used.

Requests to core: add an evaluator hook and polymorphic card signatures to
`Library`. Permit `eval(c, xs)` to resolve a quoted callback argument's code
hash in its closed scope; currently quoted `table_total` with `f = count_row`
returns `Bottom(ill_formed)` although direct evaluation returns `Ok(4)`.
The quoted `embed_z5` bridge now evaluates to `Ok(0)` in three steps on `z0`,
matching the direct bridge call. The bridge evidence uses core's commuting
verifier and metered `call_in` on both built worlds.
Make deep-stack evaluation reentrant for `call_in` on accepted worlds that
contain body ops: the current one-worker executor deadlocks when nested
`wf(w)` itself evaluates a body. The showcase avoids that path by counting
finite worlds instead of dispatching into them.
