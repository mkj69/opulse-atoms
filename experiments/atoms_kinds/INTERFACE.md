# Experiment 3 interface

Package: `atoms_kinds`; load with `PYTHONPATH=src:experiments/atoms_kinds:experiments/atoms_mul`.
The frozen task schema is `atoms_kinds.task/1`: `id`, `stage`, `family`, `arity`,
`statement`, `public_examples`, `hidden_cases`; each case has integer `args` and a list of
integer `expected` components.
Fraction results use one `Pair` value with reduced integer numerator and
positive denominator; comparison returns one integer, 0 or 1.

Learner response consists of one-line ASCII declarations: `op solve(a: Int, ...) -> Pair = Pair<n, d>`
(or `-> Int` for comparison), optional `op NAME(...) -> Int = expr`,
`obj NAME = <num: Int, den: Int> where COND canon FN sealed (make, num, den)`,
`comb @NAME[f: (Int, Int) -> Int](left: Int, right: Int) -> Int = expr`
(called as `@NAME[add](a, b)`),
and, in K4-K6, `law #NAME: eq(lhs, rhs) for a: Int, b: Int`
(saved as `save #NAME`),
in K5-K6 `obs ?numerator{p} = add(?pair_num_probe{p}, 0)` over public Pair
values, and in K6 `bridge ~to_frac: Pair -> Frac = Frac.make(x) commutes
(Pair.num -> Frac.num, Pair.den -> Frac.den)`,
and `save NAME` (each new definition must be saved). Expressions support integers,
booleans, variables, calls, `Pair<n, d>`, `let ... in ...` and
`if ... then ... else ...`. `atoms_kinds.ascii` wraps shared notation where
representable and raises only `AsciiSyntaxError`; the fraction-specific Pair
construction and combinator signature retain a compatibility adapter.
Core notation parses observations directly. The local adapter handles the
bridge's generated Frac constructor call and qualifies its same-world target;
core compact notation cannot parse this dynamic constructor expression.
The public `pair_num_probe` exposes only the already-public numerator.
Observations declare a typed public Pair input; their bounded evidence records
`non_interference: n/a` because no truth sort is observed. The current core checker
still rejects invented pure operation dependencies, despite spec 0.5 R13-D.
Definitions may depend on earlier saved definitions. Optional `L<n>` suffixes
are checked against `1 + max(dependency layers)` at save time; omitted suffixes
are computed. A mismatch is returned as learner-visible feedback.
Laws are checked on all 169 pairs in -6..6; outside that scope their
promotion conveys no claim. The core library verifies K4 laws without a local
verifier; no submitted `by #NAME` rewrites are allowed because
answers are programs rather than derivations.
Successfully saved names are immutable: a second save under an existing name is
refused without replacing the earlier definition. A refused save is removed from
the library and its callable scope, so feedback can be used to correct the same
name on the next attempt. Object promotion tests all 156 Pair representations
with numerator and nonzero denominator in -6..6; the bounded evidence records
the canon, validity, interface and seal obligations. There is no given Frac
object requiring an invented-to-given abstraction map.

`atoms_kinds.world.make_world(group)` creates the same integer atoms
`add, sub, mul, div, mod, gcd, eq, lt` in every arm; division truncates toward
zero, modulo follows Python, and gcd is nonnegative. `Library.write` is the
authoritative guard for `open_kinds`, not an experiment-side filter.
The world also declares signatures for the generated given `Pair.pair`,
`Pair.num`, and `Pair.den` operations, so saved operation bodies can depend on
them. The core object runtime supplies their implementation. All arms also
share the public Pair probe. K5 observations receive bounded evidence on 78
public Pair values; K6 bridges receive bounded commuting evidence on 47
canonical Pair representations (94 interface checks). Bridge application
outside that scope is callable without extending the commuting claim. An operation
without a task-family reference is callable but not verified or promoted;
refined objects and bounded combinators may carry scoped promoted evidence.
Bridges require a nonempty interface with at least one checked commuting pair;
partial bridges declare `where PREDICATE`, verify only values inside their domain,
and return `Bottom(outside_domain)` for values outside it. K6 reports its
observations as well as its bridges.
`atoms_kinds.harness.run` delegates episodes and checkpointing to
`atoms_mul.harness.run.run` with the `kinds` track and writes `config.json`, `results.jsonl`, `prompts.jsonl`,
`summary.json`, `analysis.json`, `analysis.md`, and `cost_estimate.json`;
its `episodes.jsonl` checkpoint and atomic final artifact writes use the shared
runner. Resume rejects changes
in hashes, policy, model, fuel or max attempts, and reuses finished episodes.
The real model actor is imported from `atoms_mul.analysis.llm_policy.LLMPolicy`;
it requires `--allow-api`, a model and an API key. Offline policies never call it.
Bootstrap methods and cost estimates import `atoms_mul.analysis` modules.
