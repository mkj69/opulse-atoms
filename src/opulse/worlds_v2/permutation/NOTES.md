# Twelve-card permutation world, v1 depth

## Notation limits

The original catalogue declaration is retained in `design_decl`. The stored
`Cycle` and `Subgroup` refinements and several operations cannot be printed
faithfully by compact notation. Only declarations that re-parse to the same
stored body appear in story `decl` and `ascii`; no aliases or simplified
refinements are published. Evaluated kernel bodies, evidence, and costs are
unchanged.

Example `text` retains the precise kernel expression even when standalone
`notation.parse_expr(text)` cannot parse it without a declared-kind context:
`Cycle` (both examples), `rotate` (fresh), `power` (both), `cycles`
(fresh), `closure` (both plus the invalid-orbit example), `Subgroup`
(both), `center` (both), and `inverse` (fresh).
The `Cycle.make`/`Subgroup.make` generated constructors have no call form in
the core expression grammar; the `@` sigil requires a declared-kind context,
which `finalize_export` does not supply when adding `ascii`. Observation
examples use the equivalent bare operation call syntax so the parsed node
still matches what the kernel evaluated.

The sealed given `permutation` is a twelve-position bijection; `I`, `R`, and `S`
are constant objects. Its declared operations are `swap` and the checked `pack`
constructor; `cards` is the granted public probe. `swap(i,j,p)` is the only
given action. The `cards` probe
reveals the full arrangement. Other layer-zero atoms construct/access finite
sequences and cards, compare/compute small integers, check bounds, or emit
explicit domain errors. `then` is a given combinator with a public kernel
unfold. The core supplies parameterized `Cycle.make`/`Cycle.base` and
`Subgroup.make`/`Subgroup.base`; these are **not** bespoke hosts.

## Tower

Display layers reflect the depth design, except `center`, which shows its honest
computed layer. `def_layer` is the computed dependency
layer. Every card is promoted with bounded (not exhaustive) evidence. The scope
column gives **inputs checked**, not the size of an unenumerated domain;
combinator slots have two authorized choices each. Counts are the actual
layer-zero steps of the showcased kernel expression (including its inputs).

| Display | Card | Kind | def_layer | Bounded scope | Example steps |
|---:|---|---|---:|---|---:|
| 1 | `Cycle` | object | 1 | 55 canonical lists plus two invalid | 10 |
| 2 | `rotate` | operation | 2 | 5 cycles x 11 starts = 55 | 102 |
| 3 | `power` | combinator | 1 | 60 input pairs, 2 unary slots | 313 |
| 4 | `cycles` | observation | 1 | 24 four-position permutations, I, R, S | 142 |
| 5 | `inverse` | operation | 3 | same 27 states | 668 |
| 6 | `sign` | observation | 2 | same 27 states | 1,601 |
| 7 | `compose` | operation | 3 | 10 x 5 pairs of four-position states | 1,889 |
| 8 | `closure` | combinator | 1 | 50 starts x 4 slot pairs, cap 4,096 | 501 |
| 9 | `Subgroup` | object | 1 | 54 distinct identity/transposition pairs | 15,702 |
| 10 | `order` | observation | 2 | same 27 states | 3,734 |
| 11 | `conjugate` | operation | 4 | 10 x 5 pairs of four-position states | 4,442 |
| 1 (last card) | `center` | observation | 1 | 54 distinct valid two-member subgroups | 204,807 |

The four-position family is bounded evidence for a family of 12-card inputs;
it is **not** a proof for all `12!` permutations. The closure verifier checks
four combinations of the named authorized slots and checks finite-orbit
bijection; it makes no claim about arbitrary slots. `@closure[reset,rotate_pair]`
on `I` is an exported kernel-run `Bottom(not_bijective)` counterexample.
Each reference operation and observable is checked against the independent
stdlib implementation in `worlds/catalogue/depth/permutation.py`.
Observation evidence covers every stated input, but checks non-interference
within batches of at most five states, not across different batches.
With subject-passing observations, `sign` and `order` call `cycles(s)` rather
than re-reading `cards` and calling `cycles` on that view. Their showcased
steps decrease by 11 and 13 respectively. Subgroup validation increases its
showcase/fresh steps from 13,653/203 to 14,182/2,264 and center's from
112,402/2,090 to 185,223/4,151; all tower values are unchanged. The fresh
`sign` and `order` examples decrease by 13 and 3 steps from the earlier
depth implementation. On the current core, refined edge entry and generated
object operations add counted steps to the showcase: `rotate` +74, `power`
+222, `inverse` +218, `compose` +190, `closure` +304, `Subgroup` +1,520,
`order` +190, `conjugate` +598, and `center` +19,584. `Cycle`, `cycles`, and
`sign` retain their showcased counts.

## Differences and adapters

- `?cycles` returns a sequence of canonical index sequences, rather than
  physically wrapping each in a sealed `Cycle` value. This keeps the observation
  strictly within its granted `cards` probe: the core observation checker
  forbids calling invented object constructors or operations. Consumers wrap
  each component with `Cycle.make` before applying `rotate`.
- `Subgroup.make` takes a finite **member list**, not an operation-slot pair.
  It checks nonempty size <= 4,096, identity membership, each member's
  permutation validity and every pairwise product's membership before sorting.
  Its checked 54-case object scope consists of distinct identity/transposition pairs.
- `?center` compares two members' index compositions directly via granted
  `cards` and generic sequence lookups. The observation checker forbids calls
  to invented `conjugate` inside an observation. Its computed layer is 1,
  rather than the design's proposed display layer 12; `power`/`closure` likewise have
  lower computed layers because their operation slots are runtime parameters.
- The single-sort observation declaration calls its full-view probe `cards`;
  the probe also exposes subgroup members as visible sequences when `?center`
  receives a `Subgroup`. This polymorphic case exceeds the declaration's
  nominal `permutation` truth sort, but does not reveal any hidden state.
  Before exposing a subgroup, the probe checks its exact canonical member
  representation, valid permutations, identity and pairwise closure; malformed
  or unclosed cards return `Bottom(invalid)`. The learner entry point and
  generated object base interfaces reject malformed invented cards as well.
  These boundary checks do not mint values under invented sorts. The refreshed
  export preserves all twelve tower values, with steps updated for core edge entry.
- The core now resolves generated object operations and checks observation
  bodies, valid/canon dependencies, and subject-passing nested observations
  directly. The declaration gives polymorphic sequence helpers the `any`
  sort instead of incorrectly declaring every sequence element an integer.
  Core verification records the exact checked-domain digest for every card.
- The remaining `PermutationLibrary.run` guard enforces valid input cards at
  the public entry. Calling bare `Library.run` with an unclosed forged `Subgroup`
  and `center` can return `Bottom(measure)` instead of `Bottom(invalid)`;
  this world checks group validity before the observation reads its members.
- Closure's explicit measured BFS is a public kernel recursion with a 4,096
  cap, not a layer-zero search host. Its set sort is represented by the
  canonical `sequence` card; only its display notation says `Set<...>`.

The full fresh export comparison is slow-marked (set `OPULSE_RUN_SLOW=1`);
the default suite checks a fresh build through the first three tower cards.
# Source printing

- Cycle: printer unavailable — dependencies cannot be represented in their current order.
- rotate: printer unavailable — invalid ASCII identifier.
- inverse: printer unavailable — invalid ASCII identifier.
- compose: printer unavailable — invalid ASCII identifier.
- Subgroup: printer unavailable — dependencies cannot be represented in their current order.
- conjugate: printer unavailable — operation metadata has no compact ASCII declaration.
