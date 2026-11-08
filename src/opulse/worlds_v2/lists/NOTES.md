# Lists depth world

Layer 0 gives finite public lists and pairs, small integer arithmetic and comparisons, structural constructors/accessors, and the public `items` and `length` probes. The world-given `then` is injected as a promoted layer-0 kernel combinator body because the core scope only includes invented bodies. A second builder `snoc` and reversed comparison `ge` extend the bounded combinator operation families. Generic indexed access and replacement are not sorting or inversion oracles. The declared list and pair carriers are `given`: the declaration validator accepts map-shaped compose tags but the current core object generator requires positional pairs for multi-field constructors. Their host operations preserve the intended list/pair representation. `NonEmpty` and `Run` use core-generated `.make` and `.base` object operations and the core object verifier; the core library checks private capabilities iteratively and the generated object accessors reject forged refine cards.

| Design layer | Card | Kind | Computed layer | Evidence (inputs) | Catalogue steps |
|---:|---|---|---:|---|---:|
| 1 | NonEmpty | object | 1 | exhaustive, 121 | 3 |
| 2 | fold | combinator | 2 | bounded, 121 x 2 builders | 25 |
| 3 | reverse | operation | 3 | exhaustive, 121 | 26 |
| 4 | palindrome | observation | 4 | exhaustive, 121 | 29 |
| 5 | Run | object | 1 | exhaustive, 9 pairs | 7 |
| 6 | rle | operation | 4 | exhaustive, 121 | 225 |
| 7 | stable_merge | combinator | 1 | bounded, 400 x 2 comparisons | 44 |
| 8 | sort | operation | 2 | exhaustive, 121 | 140 |
| 9 | merge_count | combinator | 2 | bounded, 400 x 2 comparisons | 81 |
| 10 | inversions | observation | 4 | exhaustive, 121 | 380 |
| 11 | trace | operation | 5 | exhaustive, 121 | 437 |
| 12 | certificate | observation | 5 | exhaustive, 76 | 796 |

Each 121-input unary scope exhausts lengths 0..4 over `-1..1`. Each merge scope contains all 400 ordered pairs from the 20 nondecreasing lists of length 0..3 over `-1..1`; both `le` and `ge` are verified only on nondecreasing inputs, so their public examples obey that domain. `fold` checks `cons` and `snoc` with a nil seed. The private `rle_step` checks twelve item/valid-accumulator inputs; `rle` uses `fold[rle_step]` after reversing the input. The object `Run` checks keys -1..1 and counts 0..2 including invalid zero. The certificate scope pairs all 13 lists of length <=2 with six additional length-3/4 lists, each against empty, one-step, two-step and reference-minimal traces (76 inputs). `NonEmpty.make(list.nil<>)` is the exported `Bottom(invalid)` example. The module tests also check a 512-element input against the independent depth reference.

Design deviations: card 9 (`merge_count`) uses card 7 (`stable_merge`), not card 8 (`sort`): sorted inputs are its explicit precondition, and its separate traversal counts cross-pairs. Card 12 (`certificate`) replays the proposed swaps and uses `inversions`, `sort`, and `rle`, not card 11 (`trace`), which only produces proposed steps. `rle` reverses once and folds with a verified run-update helper, prepending runs to preserve order using the invented `reverse`, `fold` and `Run`. Generated object makers wrap their base, unlike the design's bare constructors, so their example expressions use `.make`. Computed dependency layers, not display layers, govern promotion. `@fold` uses measured structural `Rec`.

World-local glue consists of the public-list observation verifier, observation parameter binding and callability. Core observation checking only allows its truth subject through probes and observation dependencies; the public list computations instead use ordinary operations and the certificate has a second input. The local verifier checks reference results, unchanged input and call unfolding and binds the exact checked domain to its evidence. Given list hosts check carrier shape but do not enforce Run positivity; the invented object constructor and core-generated accessors reject invalid values. The lexicographic-inverse showcase candidate comes from the independent depth reference and is rechecked by kernel sort/inversion; the reference proves minimality.

ASCII export: only declarations printed from the stored body and re-parsed to that same body appear as `decl` and `ascii`. The catalogue design prose remains in `design_decl`. Stored definitions, evidence, executions, traces and costs remain unchanged.

Examples not expressible by the core expression grammar: both `NonEmpty.make(...)` examples (valid and empty lists) and both `Run.make(...)` examples (pairs `(4, 3)` and `(2, 1)`). The parser treats dotted object names as constructors requiring angle brackets, not calls to generated `.make` operations. Keep these four evaluated-call texts visible without marking them `ascii`. Other examples now use exact input card literals (`list.cons<...>`, `list.nil<>`, `pair<...>`) rather than the design's flattened `List<...>`; combinator and observation sigils parse with the world kind/arity context. The shared `finalize_export` checks expressions *without* context, so sigiled examples have no `ascii` even though `notation.parse_expr(text, context)` accepts them.
## Printer limitations

NonEmpty: printer unavailable — ValueError: dependencies cannot be represented in their current order.
fold: printer unavailable — ValueError: invalid ASCII identifier.
reverse: printer unavailable — ValueError: dependencies cannot be represented in their current order.
Run: printer unavailable — ValueError: dependencies cannot be represented in their current order.
rle: printer unavailable — ValueError: dependencies cannot be represented in their current order.
sort: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
trace: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
certificate: printer unavailable — ValueError: bool cards are indistinguishable from host bools in ASCII.
