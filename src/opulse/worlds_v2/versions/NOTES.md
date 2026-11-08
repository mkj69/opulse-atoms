# Versions @1: twelve-path depth world

## ASCII notation limits

Story `decl` and `ascii` appear only when the printer's source re-parses to the
stored body's digest. The stored kernel bodies and constructor validation remain unchanged.

- patch: printer unavailable — ValueError: invalid declaration name.
- delta: printer unavailable — ValueError: invalid ASCII identifier.
- apply: printer unavailable — ValueError: dependencies cannot be represented in their current order.
- merge: printer unavailable — ValueError: invalid declaration name.
- three_way: printer unavailable — ValueError: invalid ASCII identifier.
- conflict_paths: printer unavailable — ValueError: invalid ASCII identifier.
- resolve: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
- invert: printer unavailable — ValueError: invalid ASCII identifier.
- replay: printer unavailable — ValueError: invalid declaration name.
- rebase: printer unavailable — ValueError: invalid ASCII identifier.
- merge_idem: printer unavailable — ValueError: invalid ASCII identifier.
- merge_symmetric: printer unavailable — ValueError: dependencies cannot be represented in their current order.

The six object examples (two each for `patch`, `merge`, `replay`) retain their
dotted constructor-call text: the core expression grammar cannot parse these
calls. The six combinator examples (two each for `chain`, `three_way`,
`rebase`) use genuine operation slots and parse with a kind/arity context;
`parse_expr` without a context rejects the `@` sigil, so the shared finalizer
does not mark their text `ascii`. Their evaluated inputs, outcomes, steps and
evidence are unchanged.

Layer zero supplies immutable twelve-path `Doc` and rooted `History`/`Version`
values, ordered lists, sorted `Choices`, `edit` and `fork`. The public `read`
and `read_version` probes expose documents and ancestry. `identity_doc` is a
generic document identity used as a second operation-slot family member;
other counted hosts provide constructors, projections, lists, comparisons,
small-integer arithmetic and `reject`. Text is alphanumeric or `Gone<>`.
The given `@fix` binds a named binary operation using a public kernel rule.

| Design layer | Card (kind) | Computed layer | Status / method / scope | Example steps |
| --- | --- | --- | --- | ---: |
| 1 | `patch` (object) | 1 | promoted / exhaustive / 12 paths x 4 old x 4 new = 192 | 1 |
| 2 | `delta` (observation) | 1 | promoted / bounded / 61 inputs | 48 |
| 3 | `chain` (combinator) | 2 | promoted / bounded / 61 input shapes x 4 slot assignments = 244 evaluations | 67 |
| 4 | `apply` (operation) | 3 | promoted / bounded / 61 inputs | 119 |
| 5 | `merge` (object) | 1 | promoted / bounded / 61 inputs | 1 |
| 6 | `three_way` (combinator) | 4 | promoted / bounded / 61 inputs x 4 slot assignments | 228 |
| 7 | `conflict_paths` (observation) | 1 | promoted / bounded / 61 inputs | 10 |
| 8 | `resolve` (operation) | 2 | promoted / bounded / 61 inputs | 42 |
| 9 | `commute` (observation) | 4 | promoted / bounded / 61 inputs | 347 |
| 10 | `invert` (operation) | 1 | promoted / bounded / 61 inputs | 20 |
| 11 | `replay` (object) | 1 | promoted / bounded / 61 inputs | 1 |
| 12 | `rebase` (combinator) | 5 | promoted / bounded / 61 inputs x 4 slot assignments | 922 |

Each 61-input scope is one design witness and the Cartesian product of twelve
paths with five new values (`x`, `y`, `z`, `Gone<>`, `w`). Other inputs use at
most two edits per branch and two commits; no claim covers arbitrary histories
or documents. Core combinator verification enumerates both operation slots of
`@chain` over `read` and `identity_doc` independently. The exported `apply`
failure is a stale patch producing `Bottom(guard)` without mutating the base.
Three harder showcases are checked with kernel calls; the 24-commit
deletion/reconstruction test compares with the standalone reference oracle.
Cards 2, 5, 6, 7, 9, 10, 11 and 12 use named given atoms or other
previous cards, not the immediately preceding card; the export records their
actual `def_layer` rather than inventing dependencies.

## Deviations and adapters

- The design's closures cannot be passed as data: `chain`, `three_way`, and
  `rebase` have two real FnRef slots each, checked over `read` and
  `identity_doc`. The latter two still accept public branch documents and
  explicit ordered patches rather than arbitrary closures. FnRefs are encoded
  as `{"t":"fn","v":name}`.
- Invented `Patch`, `Merge`, and `Replay` are parameterized `compose` objects.
  The core generates their constructors, tag predicates and accessors; their
  bodies are no longer callable by bare names. World-local generated
  constructors reject malformed patches, conflict records and replay
  positions; the generic `card` atom cannot mint invented sorts. `three_way`
  and `rebase` produce valid constructor arguments, while `apply` retains its
  independent guard. Their genuine `def_layer` is shown without padding.
  Their fields use the unconstrained `Value` sort: `Any` is a declared given
  object here, so generated constructors would otherwise require `Card("Any", …)`
  for every field, rejecting the scalar and document values in the tower.
- `VersionsLibrary` retains generic-`Any` static typing tolerance and
  multi-input observation verification (the core observation runner accepts
  one truth state per input). It calls core `check_object` for invented objects,
  then checks generated constructors against the independent reference on the
  exact finite domain. Core compose verification instead takes a Cartesian
  product of every `Value` input, including invalid path/text/document
  combinations, and rejects this world's deliberately constrained constructors.
  Core verifies combinators, operations and laws. Local object and observation
  evidence records the digest of the exact checked input domain.
- The rebase turn loop remains explicit measured `Rec` over commits; replace
  with core interleaving/turns combinator when spec 0.3 lands. The generic
  `reject(reason)` is needed because `Bottom` cannot be stored in a literal.

No slow-marked tests are required; the world tests finish under 120 seconds.

Two additional bounded law rows record `#merge_idem` for base12 plus eight
single-edit documents, and `#merge_symmetric` for 73 non-conflicting ordered
pairs of those documents. These laws state exactly their finite checked scope and do not
claim arbitrary histories. The twelve original tower outcomes remain exact;
the two-slot branch views add 42/39 steps to the two `three_way` witnesses
and 83/42 steps to the two `rebase` witnesses.
