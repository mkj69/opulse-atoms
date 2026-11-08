# Hidden world depth, version 1

## Layer zero and trust boundary

The sealed `Truth` holds a fixed R/B card, public history, and the receiver's own
guesses. `signal` is a trusted conditional distribution: A costs 3 with red
likelihoods (1, 1/2), B costs 1 with red likelihoods (1/4, 3/4). `receiver`
projects only public history/actions, while `judge` compares against the full
sealed state. The receiver's library scope cannot call either `signal` or
`judge`; the judge can call them only in its own capability scope. Every learner
card takes public values, never a truth handle. The declared `@bind` is a
kernel `Rec` with explicit weighted branches, exact products, and equal-value
merging. Generic constructors/accessors, list operations, rational arithmetic,
and small-integer budget operations are the only other given hosts. Exact
fractions have reduced `Rational<fraction>` cards; zero-probability policy
branches are still checked for sufficient budget.

The ten design layers and actual computed definition layers differ when a
combinator's operation slot is a variable: the slot does not statically depend
on a particular operation. Both slot families are checked against *two*
operations (`update`/`update_copy`, `value`/`value_copy`). The helper aliases
are invented operations, promoted through the same pipeline, and do not appear
as tower cards. They add one visible kernel-call layer when invoked.

## ASCII notation limitations

The export keeps the original tower prose in `design_decl`. Only `lamps` has
`decl` and `ascii` matching its stored body; other rows publish neither.
Core notation cannot print the generated dotted accessors (`Belief.make`,
`Belief.r`, `Policy.base`, etc.) or the actual refine object bases/canonicalizers.
The JSON body and stored promoted definition remain authoritative.

Only the `lamps` and `update` example texts currently round-trip through
context-free `notation.parse_expr` to the evaluated node. The remaining
examples, `Belief`, `scan`, `confidence`, `Policy`, `value`, `optimize`, `first`,
`regret`, and `scan:unpaired`, are retained as legacy display text: the core
context-free parser rejects the `@`/`?` sigils without a kind registry, and
generated dotted constructors/accessors cannot be expressed as calls. Their
texts must not be used as executable reproductions; their evaluated expression
nodes, inputs, outcomes, steps, and traces are unchanged.

| Design layer | Invented kind and card | Computed layer | Verified bounded family | Layer-zero steps in its exported example |
| --- | --- | ---: | ---: | ---: |
| 1 | observation `lamps`: public lamp projection | 1 | 64 six-step public histories | 18 |
| 2 | refine object `Belief`: normalized reduced public pair | 1 | 65 distinct normalized fractions | 15 |
| 3 | operation `update`: normalize two public likelihoods | 2 | 68 priors/modes/lamps | 140 |
| 4 | combinator `scan`: fold paired public mode/lamp streams | 1 | 112 two-step histories, 2 step operations | 878 |
| 5 | observation `confidence`: maximum posterior probability | 2 | 65 distinct fractions | 424 |
| 6 | refine object `Policy`: validated finite policy tree | 1 | 64 distinct depth-three trees | 5 |
| 7 | operation `value`: check budgets and integrate both branches | 3 | 68 conditional policy/belief/budget inputs | 803 |
| 8 | combinator `optimize`: memoized exact Bellman policy | 3 | 51 belief/budget inputs, 2 score operations | 280934 |
| 9 | observation `first`: public root mode or guessed card | 2 | 64 distinct policy roots/leaves | 362630 |
| 10 | operation `regret`: optimal minus candidate value | 4 | 68 policy/belief/budget inputs | 60449 |

Every row is `promoted` with bounded, explicitly stated inputs and contracts;
`update`, `value`, `scan`, and `optimize` also compare against the independent
reference implementation. All ten exported primary outcomes match the design
reference. `@scan[update](Belief<1/2,1/2>,Modes<A>,Lamps<>)` is an additional
kernel `Bottom(unpaired)` example. Other failures include an over-budget policy
and an impossible observation. The receiver trace cannot invoke a private
operation. The public export has learner views only; `worlds/judge/hidden.json`
holds the sealed judge views and full inputs paired by example ID. Every nested
example call uses the receiver's `Library.run` capability checks. Lamp projection
uses three public history steps, scan six, confidence two, regret three, update
one, and examples without an observed history zero. All example outcomes and
layer-zero steps account for the current core's refined entry checks; the
results, rather than the older step counts, match the original depth tower.

## Design differences and adapters

- `Belief` is a parameterized core refine object over `BeliefPair`, with
  kernel-expressed validation and canonicalization. `Policy` is a parameterized
  core refine object over the given `PolicyNode`; its valid-tree check is a
  primitive of the given finite policy-node sort. Both use generated
  `*.make`/accessor operations rather than callable object names.
- The `confidence` example uses a *different* public two-A history with the
  same 4/5 answer rather than reusing the preceding six-step `scan` input;
  `first` uses belief 1/4 rather than reusing `optimize`'s prior. These are
  intentional fresh-input review fixes.
- The `optimize` body uses `Rec(memo=True)` in the core. Its policy result,
  plain-unfolding layer-zero step counts, and tie priorities match the depth
  reference. The core caches subcalls while charging the same unfolding steps
  and reports memo work separately on `Run.work`.
- `adapter.py` supplies world-local capability filtering and the public-value
  observation check because the core observation runner is robot-state-specific.
  Observation verification compares each recorded public input under paired R/B
  sealed truths with identical receiver views, checks that public facts are unchanged,
  and separately evaluates the inlined definition for equal outcomes and steps.
  Host primitives and learner calls reject malformed tagged cards structurally,
  including forged Belief/Policy refinements; structurally valid immutable cards
  have the same meaning regardless of how they were constructed.
  The core now checks generated object accessors, validates objects and
  verifies operations and combinators; only public-value observations and
  the `value`/`optimize` checks for literal strings in Mode/Lamp slots still
  need local handling. The local verifier binds the exact checked domain.
- Layer-zero `@bind` is stored in the declaration with a public kernel unfold
  rule and is verified by the exact trace/boundary tests. The declaration is
  generated by `declaration.py`, then locked with `opulse.tasks_v2.decl --lock`.

The full fresh-export comparison is gated behind `OPULSE_RUN_SLOW=1` because
the current core's refined-entry checks make it exceed 60 seconds; the default
suite still builds all cards fresh and checks the first three against the
committed examples. The showcase enumerates up
to 128 visible seven-lamp witnesses and recomputes all three answers in the
kernel; it is part of export generation, not an unchecked narrative.
## Published source: printer unavailable

- Belief: printer unavailable — ValueError: invalid ASCII identifier.
- update: printer unavailable — ValueError: invalid ASCII identifier.
- scan: printer unavailable — printed `fail("unpaired")` re-parses as a Bottom literal instead of the stored Call body.
- confidence: printer unavailable — ValueError: invalid ASCII identifier.
- Policy: printer unavailable — ValueError: dependencies cannot be represented in their current order.
- value: printer unavailable — ValueError: invalid ASCII identifier.
- optimize: printer unavailable — ValueError: invalid ASCII identifier.
- first: printer unavailable — ValueError: invalid ASCII identifier.
- regret: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
