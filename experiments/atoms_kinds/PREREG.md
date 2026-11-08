# Experiment 3: which kind of invention helps fraction transfer?

## Dated amendment: 2026-11-05 (before regenerated dry runs; no paid run exists)

Extend the frozen open-kind ladder with K5 = K4 plus observation and K6 = K5
plus bridge. K5 may invent derived observations over public Pair values, apply
pure definitions to those values, and use the observations in answers; it may
not access sealed truth or act. K6 may additionally invent bridges from the
given Pair to its own Frac, use them in answers, and claim commuting behavior
only on the recorded verification scope. All six arms receive identical tasks,
task order, attempt count, fuel, feedback rules, and protocol text except the
one sentence listing open kinds. The primary K2-K1 and secondary K3-K2
contrasts remain unchanged; K4-K3, K5-K4, and K6-K5 are descriptive
secondary contrasts under the same eligibility and bootstrap rule. Report
verified/promoted observation and bridge counts and their scopes. Add offline
scripts for observation and bridge use, and refusals for all closed kinds.
Prior dry runs are superseded; regenerate only after this amendment.

Frozen before the dry run. This experiment does not test whether fraction arithmetic is
computable in K1: all groups have the same integer atoms and the same kernel nodes.

## Arms and tasks

`K1` opens operation, `K2` opens operation and object, `K3` opens operation,
object and combinator, and optional `K4` additionally opens law. Observations
are closed in K1-K4. K5 and K6 follow the dated amendment. All arms can save
definitions across tasks; only `open_kinds` differs.

Stage 1 contains 24 deterministic tasks (8 sums, 8 comparisons, 8 mixed-number
conversions). Stage 2 contains 16 disjoint tasks (8 fraction dot products and 8
fraction averages). The frozen files carry both public examples and hidden cases;
only public cases are shown to the learner. Inputs are signed integers, denominators
are nonzero. Answers are reduced pairs encoded as two integers or comparison bits.
Every group receives the same task order (seed 1000 + episode), examples, fuel,
attempt limit and feedback; only public Pair values are observable.

## Outcomes and decision

Primary: difference in mean per-episode stage-2 accuracy `K2 - K1`. Secondary:
`K3 - K2`; optional `K4 - K3` uses the same bootstrap, sample-size and
decision rule, reported separately. A task counts correct only if every hidden case gives the exact
canonical answer with the core kernel; invalid, Bottom and Unknown fail.
API errors are retried by the imported `LLMPolicy` up to three times. At most two
API-error tasks per stage-2 episode are excluded from its accuracy denominator;
only episodes with every frozen stage-1 and stage-2 task ID exactly once are eligible. The primary and secondary rules
apply only with exactly 40 complete eligible episodes in each compared arm;
otherwise the comparison is labelled diagnostic, not evidence.
40 episodes per group, at most three attempts per task, fuel 200000; 10000
within-group bootstrap resamples with seed 20261104 (reuse atoms_mul analysis).
Evidence for value: point difference >= 0.10 and lower 95% CI > 0.
Evidence for no value: 90% CI wholly within [-0.10, 0.10]. Otherwise inconclusive;
no optional stopping. Secondary uses the same rule, reported separately.

Descriptive outcomes: stage-1 accuracy, invented and reused kinds, stage-2 reuse
per kind, total answer length plus each distinct saved definition once, mean
unfolded layer-0 steps and boundary-visible steps per correct stage-2 task, and API errors. Compare length
and steps by the atoms_mul bootstrap median ratio (10% descriptive margin).
For dry runs report diagnostics only: scripted policies are not learner evidence.
For K4 also report saved, bounded-verified and promoted laws and their scope;
no claim about proof shortening follows from plain-program answers.

Cost estimates use the policy's 1024-token maximum output per call (40 episodes
per group, 1.5 attempts expected and three attempts worst). The expected
output assumes 300 tokens per call; inputs use the rendered prompt length / 4.
No paid run proceeds without model, price, and supervisor approval.

## Learner protocol (frozen before rerun)

Every task includes an English statement specifying its computation and output
shape, identical across arms. Learners write ASCII `op solve(...) -> Int/Pair = ...`,
optional `op`, `obj`, `comb` definitions and explicit `save NAME` lines. Prompts
display given operations (including negative division/modulo, gcd, zero errors,
and unbounded integer semantics), the given Pair object, saved definitions and open kinds
in the same ASCII notation. Every arm sees the same law, observation, bridge
and public Pair-probe syntax; only the open-kinds sentence differs.
The learner adapter delegates compatible expressions and laws to core notation;
kernel checking and `Library.write` remain authoritative. The
shared atoms_mul runner owns checkpointing and the LLM actor.
Saved operations without a declared reference remain callable, charged for
their unfolding, and have no verification evidence or promotion. Their names
never imply a reference. Refined objects are promoted only after bounded canon
totality, idempotence, validity preservation and interface respect over all 156
Pair representations with numerator and nonzero denominator in -6..6; construction
is checked against each canonical representative, and outside definitions cannot
read the sealed private interface. Evidence records method, scope, interface, and
obligations. There is no given Frac, so no abstraction map to a given object is
required. Saved names are immutable: duplicate saves are refused without changing
the prior callable. Combinators use bounded core
verification. An optional `L<n>` suffix must agree with the computed layer.

## Limitations

The learner adapter retains only incompatible fraction-specific syntax around
core notation. K1 can compute all answers using integer arithmetic. The experiment
isolates *permission* to invent, not a forced invention. Fraction objects carry
bounded evidence, not an unbounded proof of canon correctness. No paid run without
supervisor approval.
Core 0.4 resolves generated interfaces of saved invented objects as dependencies.
The object scripted policy saves `fraction_num` and `fraction_den` over `Frac`
and reuses these helpers on later tasks; their evidence is callable only, not
a claim of unbounded fraction correctness.

K4 is descriptive: the answer format is `op solve(...) = ...`, not a
derivation. Per spec 19.1, a promoted law permits a `by #NAME` rewrite step
only in derivations inside its verified scope, not an executable call, a
grading equivalence, or a shortcut for plain programs. The K4 script states a
bounded commutativity law, then answers using operations, without a rewrite.
The core library checks and verifies laws with `holds` evidence and can replay
promoted-law rewrites within their verified scope. This experiment retains
plain-program answers and reports zero *submitted* rewrite steps; a law may
only shorten a derivation, not the executable program or its layer-0 steps.
The K4 commutativity rewrite merely swaps operands and does not shorten an
answer expression; no baseline derivations are submitted for a counterfactual
proof-length comparison. No offline shortening metric is therefore defined.
