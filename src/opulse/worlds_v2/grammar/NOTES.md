# Deep grammar world (`grammar@1`)

Layer zero provides public `Word` (48 tokens, 12 numerals, depth eight), partial
`Draft` (40 rule nodes), `Rule`, `expand`, and the `yield_probe` projection from
finished drafts. A draft's private derivation is never inferred from an author's
word. Counted generic primitives construct, index, slice, concatenate and sort
finite lists; construct words, drafts, pairs and triples; and compare and compute
small integers. `seq` and `bounded_rec` have public kernel unfold bodies.

| Layer | Kind | Invented card | Checked family | Example layer-zero steps |
| --- | --- | --- | --- | ---: |
| 1 | object | `ExprTree`: finished, ordered AST | 100 completed proofs and one hole | 15 |
| 2 | operation | `split`: depth-zero operator cuts | 81 three-number words, including grouped forms | 55 |
| 3 | combinator | `chart`: all parses with algebra slots | 50 words, two operations in each of five slots (32 assignments) | 714 |
| 4 | observation | `parse_count`: chart count | 81 public words plus one equal-view copy | 58669 |
| 5 | operation | `unrank`: first-split, left-major parse | 50 words, ranks 0 and 1 | 653 |
| 6 | observation | `ambiguous`: public parse decision | 81 public words plus one equal-view copy | 229 |
| 7 | object | `Ambiguity`: same word, two distinct trees | 50 three-number witness triples | 2681 |
| 8 | combinator | `fold`: structural interpretation | 50 ranked trees, two operations in each of three slots | 648 |
| 9 | observation | `value_hist`: parse multiplicity by arithmetic value | 81 public words plus one equal-view copy | 513 |
| 10 | operation | `gap`: max minus min interpretation | 81 public words | 533 |
| 11 | operation | `invert_gap`: first matching operator pattern | 60 target/size/count requests, at most four numerals | 722410 |

All 11 depth-design example values and all three showcase answers are also
executed by the kernel and compared with the standalone depth reference. The
rank-out-of-range example exports `Bottom(rank)` with a kernel trace. The
ranked AST and witness are parameterized refined objects, not named constants.
`ExprTree.make` validates drafts. `ExprTree.base` and the unchecked
`ExprTree._pack` constructor are private to the sealed object; the trusted
`fold` definition uses the private base to interpret a finished tree.
`Ambiguity.make` validates its two trees against public ranked parses rather
than opening either base. Public examples redact all sealed tree values and
trace payloads; `worlds/judge/grammar.json` holds the full grading examples.

## Computed-layer deviations

`design_decl` retains the original pedagogical notation. Only story definitions
that the printer renders and the parser restores with the same stored body
publish `decl` and `ascii`; no replacement validation predicates or
`fail("notation_unsupported")` bodies are published. The full stored body and
contract remain in the export. The core's
`notation.parse_expr` requires a declaration context to parse observation and
combinator sigils, whereas `finalize_export` checks examples without context:
these examples retain runnable `text` under the world context but lack
`ascii` until the shared checker accepts a context. `ExprTree.make` and
`Ambiguity.make` examples cannot be written in the core expression grammar:
the dotted generated constructors are rejected even with context. Their text
remains the exact nested kernel expression used for evaluation.

The numeric `def_layer` is calculated from real dependencies, not padded to the
pedagogical tower layer: `split` needs only layer zero (1); `chart` needs
`split` (2); `parse_count` (3); `unrank` and `ambiguous` (4); `fold` uses the
layer-one `ExprTree` (2); `value_hist` uses the chart and fold (4); `gap` (5);
`invert_gap` (6). The `Ambiguity` refinement checks ranked parses at layer 5;
its examples obtain the trees through `unrank`.
The algebraic histogram uses a finite list of interpretations followed by a
counted sort and group, rather than a fused `Counter` convolution. Both count
the same multiplicities but the former is slower and explicitly retains every
interpretation. The published `bounded_rec` specializes the reference's
higher-order callback to a measurable two-branch kernel recursion: local
recursive function references are not first-class operands in this kernel.

`Rec(memo=True)` is declared on `chart`; evidence records both memoized and
plain kernel layer-zero steps and kernel work on the same three-numeral sample.
The kernel charges 228 layer-zero steps for each; work is 207 memoized versus
228 plain. These are measured kernel counts, not the reference's call counts.
`Rule` and `Hist` are declared layer-zero sorts.

The core verifies both combinators, including the mixed-arity `chart` slots;
only public-word observation verification remains local. Its evidence binds
the exact checked family through `bound_evidence`.

## Adapters and tests

`GrammarLibrary` supplies a word parameter to non-robot observations and
checks public-word outputs without reading an author-supplied draft. The
non-interference check compares every pair with the same public word in the
recorded family, including a structural copy of the first public word. This
scope contains public words, not distinct private derivations; the pairwise
condition is vacuous for the remaining unique words.
Card inputs are validated structurally and refined inputs are checked before
learner runs; given hosts return `Bottom(invalid)` for malformed cards.
The three nested constructor/ranking examples execute the complete expression
displayed, so their step counts include construction of the arguments.
The core combinator verifier checks heterogeneous-arity algebra families and
records the exact checked domain for both `chart` and `fold`. Object validity,
sealing, and promotion use the **core** object checker/verifier. The oracle is
imported only for independent verification and export assertions, never as a
given host implementation.

The normal grammar test directory stays under 120 seconds. There are no slow
tests behind `@pytest.mark.slow`; the fresh full-export comparison runs with
`OPULSE_RUN_SLOW=1` because rebuilding all cards and showcases exceeds 60
seconds. A default test freshly builds and executes the first three cards.
The earlier `build_library` cache was removed; large 12-numeral exhaustive
families are excluded from bounded evidence but the nine-numeral showcase
runs in full.
# Source printing

- ExprTree: printer unavailable — dependencies cannot be represented in their current order.
- split: printer unavailable — operation metadata has no compact ASCII declaration.
- unrank: printer unavailable — invalid ASCII identifier.
- Ambiguity: printer unavailable — dependencies cannot be represented in their current order.
- fold: printer unavailable — invalid ASCII identifier.
- gap: printer unavailable — operation metadata has no compact ASCII declaration.
- invert_gap: printer unavailable — operation metadata has no compact ASCII declaration.
