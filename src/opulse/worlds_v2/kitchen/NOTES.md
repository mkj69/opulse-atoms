# Timed kitchen (kitchen@1)

Layer zero declares ten dated stock items, six station-bound recipes, a one-tick
completion/expiry transition, a four-component initial-state constructor, and
two learner probes (`stock`, `busy`). Each raw count is 0..8. A station has
capacity one; FIFO batches preserve birth times. `seq` is a given combinator
with a public strict kernel-recursive unfold, not a host implementation. All
given recipe starts and the tick operation are checked against the independent
`worlds/catalogue/depth/kitchen.py` oracle on all 81 initial stocks in 0..2.

The generic extras are `empty`, `head`, `tail`, `cons`, `append`, `length`,
`item`, `field`, `eq`, `lt`, `le`, `add`, `sub`, `mul`, `seq_pair`, `seq_triple`, and
`query`: structure, equality, small-integer arithmetic/comparison, and
sequence construction/projection. `increasing` is a structural ascending-list
test; it rejects duplicate and unsorted simultaneous actions. `optional` is a
non-strict generic outcome-to-list primitive: a successful result becomes a
singleton; `Bottom` becomes empty, permitting an exact search to discard
invalid branches. It forwards `Unknown` rather than treating fuel exhaustion
as a failed schedule.

## Tower

The numbered positions below follow the depth design. `def_layer` is the
actual dependency layer, not padded to match the position. All evidence sizes
refer to exact input evaluations, not the entire unbounded kitchen domain.

The public story keeps the design prose under `design_decl`; `decl` is present
only when the core printer emits a declaration that parses to the stored body.
Plan: printer unavailable — invalid ASCII identifier.
peak: printer unavailable — invalid ASCII identifier.
reach: printer unavailable — operation metadata has no compact ASCII declaration.
yield: printer unavailable — invalid ASCII identifier.
Order: printer unavailable — invalid ASCII identifier.
meets: printer unavailable — invalid ASCII identifier.
earliest: printer unavailable — invalid ASCII identifier.
score: printer unavailable — invalid ASCII identifier.
best: printer unavailable — dependencies cannot be represented in their current order.
min_flour: printer unavailable — invalid ASCII identifier.

Two example texts remain in their evaluated, sigiled notation without an
`ascii` field: `filter_plans` and `best` need operation-slot references that
`notation.parse_expr` cannot parse without a library context. The query
examples use core `query(state(...), make_order(...))` calls rather than the
independent oracle's `?name{Query<...>}` syntax. All examples retain their
original full inputs and outcomes; the other eleven texts parse context-free.

| Position | Card | Kind | Verified scope | Example layer-0 steps |
|---|---|---|---|---|
| 1 | slot | combinator | 81 raw states x 4 action tuples (324), bounded | recorded in export |
| 2 | Plan | object | 50 valid one-slot raw records, bounded | recorded in export |
| 3 | peak | observation | 50 idle + 18 delayed-mix plans (68), bounded | recorded in export |
| 4 | reach | operation | 25 raw states x horizons 0..2 (75), bounded | recorded in export |
| 5 | yield | observation | 60 one-idle-slot plans, bounded | recorded in export |
| 6 | Order | object | 3x3x3 target triples x deadlines 5,6 (54), bounded | recorded in export |
| 7 | meets | operation | 25 idle plans x 3 orders (75), bounded | recorded in export |
| 8 | filter_plans | combinator | 20 prefix lengths x 3 orders x 2 predicates (60 inputs), bounded | recorded in export |
| 9 | earliest | observation | 25 raw states x targets 0,1 at deadline 1 (50), bounded | recorded in export |
| 10 | score | operation | 60 one-idle-slot plans, bounded | recorded in export |
| 11 | best | combinator | 25 prefix lengths x 2 orders x 2 metric operations (50 inputs), bounded | recorded in export |
| 12 | min_flour | observation | 25 raw states x targets 0,1 at deadline 0 (50), bounded | recorded in export |

Helper cards `PlanData` and `OrderData` are genuine positional compose objects;
`Plan` and `Order` are locally verified refinements over them. `make_plan` replays
each slot, then the refine constructor checks its unique end; `make_order`
checks the four public integer bounds. `score_alt` provides a second metric
operation in `best`'s verified slot family. All object tags are positional
field/sort pairs, avoiding the core's known named-map compose bug.

Position and definition layer are distinct: card 4 (`reach`) calls `slot` and
`make_plan`, not card 3 (`peak`); card 5 (`yield`) reads `Plan.end`, not card 4;
card 6 (`Order`) refines `OrderData`, not card 5. Card 8 (`filter_plans`) accepts
`meets` as an operation slot rather than hard-coding card 7. Card 10 (`score`)
uses `meets` and `Plan.end`, not card 9; card 11 (`best`) accepts `score` as a
metric slot rather than hard-coding card 10; card 12 (`min_flour`) searches
`reach` and filters with `filter_plans`, not card 11.

## Design differences and adapters

- The declaration provides `seq` as a full combinator specification in its
  library; layer one starts with `slot`. `slot` takes a sequence of recipe
  names instead of variadic operation slots. This keeps station validation
  compositional across six recipes.
- `Plan` carries its computed end inside a sealed refine over a positional
  `PlanData` record. `make_plan` is a separately verified layer-three operation,
  not an unchecked constructor. `Order` similarly refines `OrderData`.
  Public examples spell plan arguments as `make_plan(start, slots)` so their
  complete sealed end is replayed, not guessed from a two-field literal;
  recorded steps and traces include these nested construction calls.
- `reach` keeps one fewest-starts, lexically first witness per complete state.
  Horizons above two are computed by the same kernel but are not part of its
  bounded evidence. The output frontier retains discovery order, whereas the
  reference sorts it by slot list; the depth examples have the same order.
  Cross-check larger instances independently.
- The superseded inventory-only `hosts.py`, `adapter.py`, and `story.py` were
  removed; the timestamped `depth_story` is the only exported tower.
- The local `depth_adapter.py` checks constructor/accessor round trips on the
  exact declared families for both composed objects. Core now checks generated
  references and verifies ordinary operations/combinators; local checks remain
  for the heterogeneous frontier tuples, the design's layer-one `Order`, and
  parameterized observations. Every local witness binds its checked-domain
  digest. Core's compose verifier takes a Cartesian product of all finite
  integer candidates for `OrderData`, so that 64-row family remains local.
- Kitchen's given `List` values are host tuples. The local `PlanData.record`
  constructor accepts those tuples while checking both `State` fields; the
  generic compose constructor expects a `Card` for every declared object sort.
  The local `Plan._stored` validates the tuple-backed positional record before
  core's generated refinement constructor checks its validity; without it the
  new output-entry guard rejects even freshly constructed plans.
  Refinement verification checks generated accessors available at that point;
  later public operations remain in the sealed interface. The fixed `meets`
  predicate in `best` is recorded as a dependency at its actual layer.
- Derived observations `peak`, `yield`, `earliest`, `min_flour` use only granted
  `stock` and `busy` probes for raw quantities. The adapter enforces named probe
  permissions and compares bounded observations with independent references
  and with every other publicly indistinguishable input in the recorded family;
  core's robot-specific observation verifier cannot handle these parameterized
  `Plan` and `Query` values. Current adapter does not prove the full core I3
  non-interference obligation for arbitrary non-initial states; evidence is
  limited to the stated initial-state families.
- `earliest` reconstructs the four raw amounts from `stock`; it is consequently
  defined for the exported raw initial queries, not arbitrary non-initial state
  histories. Before searching it proves a safe lower bound from sequential oven
  occupation and the first possible cake/bread/plate completion; deadlines
  below that bound return `Bottom(no_plan)` without enumerating states.
  `min_flour` likewise presupposes a raw initial state. These are
  explicit limitations rather than claims of universal planning.
- `min_flour` proves every flour count below `2*bread + cake + dessert`
  impossible by recipe input conservation (no search required), then performs
  full-state reachability at the absolute deadline for each remaining
  candidate. This is equivalent to the oracle's exhaustive 0..8 search for
  raw states with nonperishable finished products but avoids redundant searches.
- Exact depth showcase searches at horizons 8 and 9 are much slower through
  the recursive kernel than the optimized standalone oracle. Consequently the
  exported `earliest` and `min_flour` examples are smaller, independently
  checkable kernel runs (a deadline-4 impossible bread and a zero-order inverse
  query) instead of the design's 6 and 3; the original examples and all three
  showcase answers are independently checked by the design reference script,
  but **not** by kernel executions at their full horizons. Do not treat an
  `Unknown(fuel)` as `Bottom(no_plan)`. The `Bottom(stock)` failure example
  comes from `slot`.

The example outcomes and per-example layer-zero steps are generated by
`python -m opulse.worlds_v2.kitchen.export`; full example inputs and judge
views belong in `worlds/judge/kitchen.json`, while the public export retains
only learner inputs and stock/busy projections of state-valued results.
Source
Python code and English descriptions are ASCII except design Chinese copied
into `_zh` fields. The published showcase includes compute, inverse, and
impossibility tasks from the reference design.
