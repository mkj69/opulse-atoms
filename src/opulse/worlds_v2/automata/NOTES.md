# Automata depth, version 1

## Layer 0

The alphabet is `a,b`; a DFA has dense states, a total transition row for both letters, one initial state and sorted final states. `machine_valid` accepts up to 20,000 states. The named given machines include mod-7, mod-5, mod-35, no-`bb`, seen-`b`, ends-`a`, even-length and never-accept; `depth_examples` is their exact Card representation. `to_card` and `from_card` are inverses. `count_a`, `count_b`, `step`, `distinct_count` and the `accept`/`size` probes implement the design's given vocabulary. `fold` is a kernel-measured, real operation-slot combinator, not a host; the older `fold_word` remains for compatibility.

Other hosts are only structural constructors/accessors, finite-list primitives, word append, object validation, arithmetic and comparison. `Pair` and `Trim` use generated object operations from the core. The five additional structural probe *aliases* (`step`, `start`, `final`, `count`, `machine_valid_atom`) grant access to the already-public full DFA table; they do not introduce any new state-dependent host behavior. The world is full-visibility, not sealed-truth. The given-object names in the declaration describe the fixtures; their machine values are passed as Card inputs, not zero-argument host constructors.

## Tower

Each row is a real invented definition promoted through write, check, make_callable, verify, account and promote. The example steps below are exact layer-zero costs of the first exported example, not graph vertices. Every graph answer is computed by the kernel; bounded evidence specifies an actual family of complete two-state machines, not a word-length sample.

| Design layer | Card (kind) | Computed layer | Evidence | First example steps |
| --- | --- | ---: | --- | ---: |
| 1 | `Pair` (object) | 1 | 100 pairs, constructor cross-checked | 7 |
| 2 | `sync` (combinator) | 2 | 50 paired inputs x 4 slot assignments | 14 |
| 3 | `combine` (operation) | 3 | 52 pairs/modes, complete product graph oracle | 1,650 |
| 4 | `empty_language` (observation) | 2 | 50 complete DFAs, full reachable closure | 680 |
| 5 | `Trim` (refine object) | 2 | 50 DFAs, canon total/idempotent/valid | 2,774 |
| 6 | `refine` (combinator) | 3 | 50 DFAs x 2 distinct move operations | 6,797 |
| 7 | `minimize` (operation) | 4 | 50 DFAs, canonical graph oracle | 7,937 |
| 8 | `equivalent` (observation) | 5 | 50 pairs, complete canonical automata | 54,648 |
| 9 | `separate` (operation) | 6 | 50 pairs, first BFS XOR witness | 123,717 |
| 10 | `included` (observation) | 6 | 50 pairs, directed-difference closure | 399,360 |

`reachable` (operation; 50 DFAs) and `reverse_move` (operation; 200 machine/state/letter cases) are additional promoted helpers, not design cards. `reverse_move` swaps the two letters and supplies a genuinely different operation-slot family to both combinators. `refine` performs bounded monotone finite partition splitting through measured kernel recursion: **replace with core combinator when spec 0.3 lands**. The three showcases are separately recomputed from actual kernel runs: 71 states, `aabababababa`, and language equivalence. A failed `sync` call on letter `c` exports a kernel `Bottom(invalid)` with its trace.

## Deviations and adapters

The export retains each tower's design text in `design_decl`; only `equivalent` currently prints and re-parses to the real stored body, so it is the only story row publishing `decl` and `ascii`. All rows bind their actual stored bodies with `body_sha256`. No hand-written sketches are published as definition source.

Example expressions that cannot be written **exactly** in the context-free `notation.parse_expr` grammar retain their original design text: both `Pair` examples (generated dotted constructor and helpers; marked `[generated Pair.pair]` because the unmarked card literals parse as a different expression), both `sync` examples and its invalid-letter example (operation-reference slots and dotted `Pair` constructor), both `Trim` examples (generated dotted calls), and both `refine` examples (operation-reference slots and generated dotted calls). The other examples print from the evaluated expression and round-trip through `notation.parse_expr` without context. Contextual `@sync[step,step]` is also rejected by the context-free parser used by the shared export finalizer.

Computed dependency layers do not pad to design positions: `empty_language` uses `reachable`, not `combine`; `Trim` uses `reachable`, not `empty_language`; `minimize` uses `refine` and `Trim`, not `empty_language`; `included` uses `equivalent` and `empty_language`, not `separate`. `Trim` declares every operation referenced by its `valid` and `canon` expressions. The observation adapter supports explicit public DFA input parameters because the core observation runner currently assumes a single truth state supplied through robot-style probes. `empty_language` grants exactly the `start`, `step`, and `final` probes needed by its reachable-state traversal. The adapter checks unchanged inputs, exact reference results and inlining for each domain member; it records dependency/non-interference for the fully visible deterministic machine. The core verifies `Trim` and all ordinary operations; local verification remains for `Pair` (its initial row and capacity depend on both machine arguments) and `sync` (deep-copying the domain loses the provenance of minted `Pair` cards). Each local evidence record binds the exact checked domain. The `AutomataLibrary` adapter provides checking-only signatures for core-generated `Pair.*` and `Trim.*` operations. No generated object is called by its own name.

The `combine` invalid-mode branch constructs an invalid DFA rather than dividing by zero: both paths still yield `Bottom(invalid)` at runtime, but the former has the required `automaton` output sort under strict checking. The current core's generated `Trim.base` includes structural, validity and canonicality checks; this changes downstream kernel step counts without changing any tower value or evidence domain. All exported evidence includes the current atoms hash and the digest of its checked inputs.

The design's `Pair` carries an explicit initial-state pair and Cartesian capacity; its constructor and accessors reject invalid machine inputs, initial rows, capacities, and forged cards while delegating valid construction to the core object constructor. The ASCII notation renders it as `Pair<left,right>`. `Trim` is a parameterized refinement of a DFA with BFS canonicalization, accessed through `Trim.make` and `Trim.base`; its generated pack/base interface tracks provenance to reject forged cards without moving canonicalization into a host. Identity provenance is local to a library instance: a serialized `Pair` or `Trim` card must be reconstructed through its constructor. The design describes the shortest-witness `none` result as optional; the kernel represents it as the string `none`, distinct from the empty-string witness. Export traces use `trace_json` with 18 retained call nodes and accurate total steps; truncation keeps the file below 3 MB. The `cost.steps` interval describes the verification family, while `example_steps` includes the displayed large examples. The finite structural observation adapter compares full public-probe signatures across every verified DFA and separately runs two reconstructed equivalent inputs before recording non-interference.

The representation validates up to 20,000 states, but building such a large product in the current recursive kernel has not been certified: recursion depth, tracing memory and wall time can become limiting. The exported ladder's large resource bounds are prospective task sizes, not a claim that this verifier exhaustively checked 20,000-state products. Scopes in this version verify the explicitly stated 50-200 input families and the three larger showcases.

## Tests

The default world tests check both fresh examples per card, the independent design reference, every promotion/evidence scope, randomized small-DFA unfolding and boundary invariance, invalid object/failure cases, ASCII export strings, declaration locks and the committed showcases. The complete byte-for-byte regeneration assertion is `@pytest.mark.slow` and requires `OPULSE_RUN_SLOW=1`; it builds all large kernel traces and showcases afresh. `build_library()` and `build_export()` no longer memoize previous results.
# Source printing

- Pair: printer unavailable — printed source re-parses to a different body.
- sync: printer unavailable — invalid ASCII identifier.
- combine: printer unavailable — invalid ASCII identifier.
- empty_language: printer unavailable — bool cards are indistinguishable from host bools in ASCII.
- Trim: printer unavailable — dependencies cannot be represented in their current order.
- refine: printer unavailable — invalid ASCII identifier.
- minimize: printer unavailable — invalid ASCII identifier.
- separate: printer unavailable — operation metadata has no compact ASCII declaration.
- included: printer unavailable — bool cards are indistinguishable from host bools in ASCII.
