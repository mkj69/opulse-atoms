# Pixels depth world, version 1

## ASCII publication limits

Tower `decl` and `ascii` appear only when the printer's source re-parses to the
stored body's digest; `design_decl` retains the original catalogue prose.
The verified body and its evidence remain in the export.

- islands: printer unavailable — ValueError: bool cards are indistinguishable from host bools in ASCII.
- Island: printer unavailable — ValueError: dependencies cannot be represented in their current order.
- flood: printer unavailable — ValueError: invalid ASCII identifier.
- grow: printer unavailable — ValueError: invalid ASCII identifier.
- map_components: printer unavailable — ValueError: bool cards are indistinguishable from host bools in ASCII.
- holes: printer unavailable — ValueError: bool cards are indistinguishable from host bools in ASCII.
- Shape: printer unavailable — ValueError: invalid ASCII identifier.
- signature: printer unavailable — ValueError: invalid ASCII identifier.
- euler: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
- equivalent: printer unavailable — ValueError: invalid ASCII identifier.

The following example expressions cannot be represented **exactly** by
`notation.parse_expr` without changes to the core grammar: `Island` and `Shape`
constructor examples, and the `grow`, `map_components`, `dihedral`, and
`signature` main examples. The main `map_components` and `dihedral` expressions
also contain combinator operation references. Both `scan_add` examples use
operation slots and cannot parse without a context, as does the fresh
`map_components` example. These examples keep their original design text; their
actual evaluated nodes, values, traces, and steps are unchanged in the export.

## Layer zero

`Grid` holds 1..32 by 1..32 rectangular rows of `.` and `#`; `Pt<x,y>` is an integer coordinate. `A0`, `A1`, and `B0` are the public 12x12 design constants. `light`, `erase`, and `identity` are the given operations; `?pixels` and `?area` are public probes. `@then` has a given public kernel unfold rule. The declared `island` and `shape` carrier sorts support existing layer-zero signatures; they have no host constructors. `Island.make` and `Shape.make` instead come from the core object pipeline. Generic accessors defensively validate the complete grid and nested invented-value representation (connected `Island`, cropped `Shape`) before reading; they never mint invented values. No `fn_ref` shim exists: operation slots are core `FnRef` values, encoded as `{"t":"fn","v":name}`.

Additional layer-zero hosts are generic row/coordinate accessors, grid and list constructors, integer arithmetic/comparison, list traversal/concatenation, complete text formatting, and `fail` for an explicit `Bottom`. In particular, no host counts components, crops shapes, computes signatures or searches candidates. Observations first use the granted `pixels` probe, reconstruct a public grid, and perform all subsequent operations on that probe-derived value; they never read their original argument with a world operation. `from_card` decodes the generated refinement wrappers so generic accessors can read public pixels, and `to_card` is bijective on valid grid rows. No hidden truth exists.

## Invented tower

The core verifies objects and operations against **every** listed input. For combinators, its full unfolding check runs on one input per operation-slot family; the local verifier then compares every listed input and slot against the independent depth oracle using the kernel. For public parameterized observations, the local verifier compares every input and checks direct-vs-inline unfolding and boundary equivalence on the first and last members. Both local verifiers bind the digest of their exact checked domains; the core records that digest for objects and operations. Object checks include every reference in `valid` and `canon`; a separate slow test checks every 3x3 constructor outcome against the oracle. The computed dependency layer is distinct from the design presentation layer where indicated. `holes` uses generic primitives, not `@map_components`; `@scan_add` calls the supplied `f` slot rather than hard-coding `euler`. Neither depends on the preceding design card. Example step counts are kernel-generated in `docs/assets/data/worlds_v2/pixels.json`.

| Design / dependency layer | Kind and definition | Promotion method and precisely checked domain | Example steps |
| --- | --- | --- | ---: |
| 1 / 1 | observation `islands`: count lit components | exhaustive: all 512 grids of size 3x3 | 5341 |
| 2 / 2 | object `Island`: validate connected nonempty grid | exhaustive: all 512 3x3 constructor inputs | 2288 |
| 3 / 3 | operation `flood`: reach lit neighbors of a seed | bounded: all 2304 lit seeds across all 512 3x3 grids | 2648 |
| 4 / 3 | operation `grow`: illuminate neighboring cells | bounded: all 218 connected 3x3 islands | 9569 |
| 5 / 4 | combinator `@map_components`: transform and merge each island | bounded: all 512 3x3 grids with both `grow` and `identity` slots | 90232 |
| 6 / 1 | observation `holes`: count enclosed dark components | exhaustive: all 512 3x3 grids | 12374 |
| 7 / 3 | object `Shape`: canonically crop an island | bounded: all 218 connected 3x3 islands | 15828 |
| helper / 4 | operation `turn`: quarter-turn shape | bounded: all 151 distinct canonical shapes from 3x3 islands | 7155 |
| helper / 4 | operation `mirror`: reflect shape | bounded: all 151 distinct canonical shapes from 3x3 islands | 7097 |
| 8 / 5 | combinator `@dihedral`: eight shape transforms | bounded: all 151 shapes with `identity` and `turn` slots | 53867 |
| 9 / 6 | observation `signature`: smallest dimension-prefixed pattern | bounded: all 151 shapes | 57450 |
| 10 / 2 | operation `euler`: islands minus holes | exhaustive: all 512 3x3 grids | 17716 |
| 11 / 7 | operation `equivalent`: compare component signatures | bounded: all 64 ordered pairs of eight specified 3x3 masks | 1053557 |
| 12 / 1 | combinator `@scan_add`: search single-cell additions | bounded: 50 specified 3x3 grids with at least six lit cells, targets 0 and 1, and both `euler` and `islands` slots | 1986247 |

The public export includes runnable `A0`, `A1`, and `B0` fixtures with full rows, encoded values, and constant expressions. Story `layer` preserves the original catalogue order; `def_layer` reports computed dependency depth, including independent `holes` and slot-based `scan_add`. The failure example `flood(A0, Pt<0, 0>)` is `Bottom(empty)` and an out-of-range seed is `Bottom(range)`. The 12x12 tower examples, three showcases, and separate fresh 4x4 examples are evaluated through the kernel; `trace_json` retains the first 32 calls per example with exact total steps and omitted-node counts so the export stays below 3 MB.

## Design differences and adapters

- Core refinements return `Bottom(invalid)` for disconnected `Island.make` inputs, whereas the standalone reference calls this failure `Bottom(disconnected)`; valid values and all catalogue examples agree. `Shape` refines `Island`, canonicalizing by a minimal cropped island through `Island.make`. This replaces the earlier host carrier constructors and invented-object callable shim.
- The independent `holes` and `euler` constructions have computed layers 1 and 2; the slot-based `@scan_add` has computed layer 1 because the operation supplied in its slot is not a fixed dependency. `@then` is world-given, declared as a complete kernel spec in `combinators.library` and promoted into scope by the core.
- `PixelsLibrary` remains an **adapter** for public parameterized observations, full-domain combinator reference checks, and the world-specific generic grid/list type checker. The core observation verifier expects a different sealed-state probe model; its combinator verifier doubles each costly kernel evaluation by unfolding every input. The core handles object and operation verification, one sample per combinator slot, constructor generation, and operation slots. The world uses ordinary `Rec`, not a custom fixpoint or memo combinator. During a core verification batch the adapter reuses one scope and suspends redundant world fingerprint checks, restoring normal sync afterward; nothing is stored in a definition.

## Slow evidence

`test_full_three_by_three_promotion_evidence`, `test_all_three_by_three_object_constructors`, `test_large_design_examples_exact` (indices 10 and 11), and `test_export_matches_builder` are marked `@pytest.mark.slow` and skipped in the default pixel test directory. Run them with `OPULSE_RUN_SLOW=1`. Every `build_library()` invocation verifies each definition against its entire recorded family before promotion. When supplied, the committed evidence fixture is only compared against freshly computed evidence and costs; it cannot replace verification. The default suite restores the committed evidence for examples only after checking its content, atom, and exact domain digests; it also freshly verifies the first three definitions separately. The export runs the full audit again; `PIXELS_EVIDENCE_FIXTURE` enables comparison with a previous audit, not reuse of its conclusions.

The full promotion audit takes minutes; the default pixel test command independently audits the committed fixture and skips the five slow cases.
