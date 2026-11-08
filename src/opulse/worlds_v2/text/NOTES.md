# Weighted Word Lattice (`text@1`)

Layer zero admits at most 64 code points over `a`, `b`, and space, natural-number
weights and indices, lists, pairs, options and half-open spans. The five domain
operations are `concat`, `slice_text`, `add`, `sub_nat`, `length`; the public
`chars` probe reveals indexed code points. `@map_chars` has a public recursive
kernel unfold and requires a valid one-character result. Generic counted
constructors, accessors, comparisons, list operations, identity and tag tests
are the only additional layer-zero hosts. No host counts parses or builds edges.

| Tower | Kind | What is built | Definition layer | Example layer-zero steps | Evidence |
| --- | --- | --- | ---: | ---: | --- |
| 1 `Word` | object | Refine nonempty, spaceless text | 1 | 15 | bounded 56 texts, lengths <= 4 |
| 2 `split` | operation | Maximal word runs | 2 | 54 | bounded 56 texts, lengths <= 4 |
| 3 `rewrite` | combinator | Transform and join words | 2 | 32 | bounded 56 lists, two unary slot operations |
| 4 `starts` | observation | Positions of nonspace runs | 1 | 24 | bounded 56 texts, lengths <= 4 |
| 5 `Lex` | object | Canonically sorted weighted dictionary | 2 | 254 | bounded 50 dictionaries and 5 duplicate-word lists, <= 6 words |
| 6 `edges` | operation | All matching half-open spans | 3 | 1961 | bounded 55 text/dictionary pairs, text <= 6 |
| 7 `routes` | combinator | Generic topological path fold | 2 | 267 | bounded 55 edge lists, four slot combinations |
| 8 `parses` | observation | Exact total path count | 4 | 2263 | bounded 55 text/dictionary pairs, text <= 6 |
| 9 `best` | observation | Minimum weight or `None<>` | 4 | 2282 | bounded 55 text/dictionary pairs, text <= 6 |
| 10 `optimal_count` | observation | Count of tied minimums | 4 | 2324 | bounded 55 text/dictionary pairs, text <= 6 |
| 11 `Parse` | object | Valid complete parse certificate | 3 | 594 | bounded 63 valid and 5 invalid text/dictionary/certificate triples |
| 12 `kth_optimal` | operation | Ranked optimal parse or `Bottom(index)` | 5 | 19028 | bounded 55 text/dictionary pairs, text <= 6 |

The source tower's `layer` is the curriculum order; `def_layer` is the actual
dependency layer. In particular, `starts` only needs the public `chars` probe,
`routes` only needs generic list primitives and the edge sort, and `rewrite` does not need to
call `split` when given an already split word list. Each bounded family is
checked against the independent `worlds/catalogue/depth/text.py` semantics.
`Parse.make` rechecks its nested `Lex` and `Word` refinements, including their
canonical representation, so forged cards cannot masquerade as valid certificates.
The exported `cost.steps` maximum applies to the recorded verification family,
not arbitrary longer examples; `cost.example_steps` records the displayed runs.
The three showcase answers are recomputed by promoted kernel cards, not
copied from the design. The exported kernel failure is an out-of-range rank
on empty text. For long inputs use exact integer arithmetic; no truncation.

**Deviations and adapters.** Layer-zero `Text`, `Char`, and `Nat` are declared
as given host sorts rather than core `refine` wrappers: valid code points and
exact natural numbers remain host values, not additional `Card` wrappers.
`List` is a core compose object; `Pair`, `Option`, and `Span` are named given
cards with generic layer-zero constructors/accessors to preserve their
layer-zero behavior. Invented refinements use `host_text`, `host_list`, and
`host_pair` base labels for values validated by their kernel `valid` nodes:
core accessors otherwise reject a host string as a given `Text` card and reject
generic `List<any>` elements as `any` cards. No host mints invented sorts. `Lex` uses
generic deterministic structural sorting; its valid domain ensures this agrees
with word ordering. The public truth is wholly revealed by `chars`.
`public_text` reconstructs the observation's input exclusively from that
probe before its parsing computation. `TextLibrary` bridges parameterized
public observations to the core's single-state observation API; it checks
the reference, kernel unfolding, input immutability and non-interference on
the exact declared family, including its checked-domain digest. Its type checker ignores only sort errors between
the layer-zero generic `any` and `List`/`Pair` cards. The core resolves generated
refinement operations and verifies objects and combinators directly.
Replace the remaining adapter with core observation parameterization when available. The core already supplies memoized
recursion (spec 0.3); no extra world-given memo combinator is necessary.

The targeted test family includes all twelve published values, the reference
implementation, boundary unfolding, host-domain failures, sealed constructor
errors, exact 48-codepoint counts, promotion guards, declaration round-trip,
committed export, and ASCII notation. No slow-marked tests are required.

The exported `design_decl` retains the depth catalogue's prose and design layers;
`decl` and `ascii` appear only for source that re-parses to the stored body.
The `body` and evidence fields remain the authoritative checked implementation.

- Word: printer unavailable — ValueError: dependencies cannot be represented in their current order.
- split: printer unavailable — ValueError: invalid ASCII identifier.
- rewrite: printer unavailable — ValueError: invalid ASCII identifier.
- Lex: printer unavailable — ValueError: invalid ASCII identifier.
- edges: printer unavailable — ValueError: invalid ASCII identifier.
- parses: printer unavailable — TypeError: operation references are only valid inside combinator slots.
- best: printer unavailable — TypeError: operation references are only valid inside combinator slots.
- optimal_count: printer unavailable — TypeError: operation references are only valid inside combinator slots.
- Parse: printer unavailable — ValueError: invalid ASCII identifier.
- kth_optimal: printer unavailable — ValueError: invalid ASCII identifier.

The three constructor examples (`Word.make`, `Lex.make`,
`Parse.make`) cannot be expressed as core expressions: the parser treats a dotted
object name as a tagged literal and requires `<...>`, not a call with `(...)`.
Their evaluated invocation text is retained without an `ascii` field. Combinator
and observation expressions require the definition-kind/arity context when parsed;
the shared context-free `finalize_export` consequently leaves off their `ascii` fields.
