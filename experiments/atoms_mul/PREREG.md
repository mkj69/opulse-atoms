# Pre-registered analysis plan: is multiplication innate or invented?

Status: draft by the experiment lead, 2026-11-04. Frozen when the supervisor approves the
real run; any later change must be written in a dated "Amendments" section below and the
analysis must report both the original and the amended result.

## Question

Does a definition library help a learner that must invent multiplication, compared with
a learner that cannot save definitions, and how does an invented multiplication compare
with a given one?

## Groups (design doc section "first experiment")

| group | world operations | saving definitions across tasks |
|---|---|---|
| A | add, sub, succ, pred, is_zero, eq, lt, **mul** | yes |
| B | add, sub, succ, pred, is_zero, eq, lt | yes |
| C | add, sub, succ, pred, is_zero, eq, lt | no |

A and B differ only in `mul`. B and C differ only in the library. Inside one task every
group may write local helper definitions and recursion (combinators var, lit, call, let,
if, rec).

## Tasks (frozen files, `tasks/stage1.json`, `tasks/stage2.json`)

- Stage 1: 24 tasks that need repeated addition; no statement names multiplication (banned
  word list in INTERFACE.md section 5). Families: 8 constant_scale (k copies of x),
  8 variable_scale (a copies of b), 8 compound (for example a copies of b plus c).
- Stage 2: 16 unseen dot-product tasks (sums of pairwise products of 2, 3 or 4 pairs,
  described as orders, scores or weights).
- Each task: 3 public examples, 12 hidden tests. Grading is exact: every hidden test must
  give `Ok(expected)` in the exact interpreter. `Unknown` (fuel) is wrong.

## Two tracks

The experiment runs in two worlds with the same groups, stages, procedure, outcomes and
decision rule (board 11-04 17:05: the first experiment uses the integer and computer
worlds):

- **Integer track (`aml`, primary)**: natural numbers, layer-0 operations add, sub, succ,
  pred, is_zero, eq, lt (+ mul in A); learners write AML definitions with recursion.
  Tasks `tasks/stage1.json`, `tasks/stage2.json`.
- **Machine track (`machine`, pre-registered replication)**: the computer world
  (`computer@1`; A = `computer_a` with the given mul r0 := r1 * r2 mod 256); learners write
  MASM subroutines with jumps. Tasks `tasks/machine_stage1.json`,
  `tasks/machine_stage2.json` (same families; results wrap modulo 256; judged on r0).

Each track is analysed on its own results file with the rule below; tracks are never
pooled. The primary conclusion comes from the integer track. The machine track is
reported next to it: if both tracks give the same decision, the report says so; if they
differ, the report gives both decisions and does not combine them.

## Procedure

- One episode = 24 stage-1 tasks, then 16 stage-2 tasks, both in an order fixed by seed
  `1000 + episode` (same order for every group). The library starts empty each episode.
- Model sampling seed = `1000 + episode + offset`, with offsets A = 0, B = 100000,
  C = 200000. Task order still uses `1000 + episode` in every group.
- Up to 3 attempts per task with feedback on public examples only.
- Model, temperature 0.7, max 1024 output tokens per attempt: same for every group. The
  model is chosen by the user before the run (open item).
- Episodes per group: **N = 40** (episodes 0..39). Groups run with independent sampling.
  The analysis constant `PLANNED_EPISODES` in `atoms_mul/analysis/analyze.py` enforces this number.

## Outcomes

Primary: stage-2 accuracy per episode (share of the 16 stage-2 tasks correct), compared
between B and C.

Secondary (all per episode, reported for every pair A-B, B-C, A-C):
1. Stage-1 accuracy.
2. Invention: the episode has at least one definition that passes the exhaustive
   multiplication check (a, b in 0..15) in the exact interpreter.
3. Reuse: share of stage-2 tasks whose final solution reaches a library definition saved
   in an earlier task (A and B only).
4. Total length: sum over all 40 tasks of the final program length, where a saved
   definition is charged once (in the task that wrote it) and library calls are free.
5. Steps: mean over correct stage-2 tasks of the layer-0 steps summed over the hidden
   tests; also the same at the library boundary (each library call is one step).

## Statistics

- Unit of analysis: the episode (tasks inside an episode are dependent).
- Difference of group means of the per-episode outcome; 95% and 90% percentile bootstrap
  confidence intervals from 10,000 resamples of episodes within each group, seed 20261104.
- Equivalence margin for accuracy: delta = 0.10 (10 percentage points).
- Length and steps: compare medians; report the ratio B/C with a bootstrap 95% CI; margin
  10% relative.

## Decision rule (primary, B vs C, stage-2 accuracy)

- **Library adds value**: lower bound of the 95% CI of (B - C) > 0 and the point estimate
  >= 0.10.
- **Library adds no value** (design doc section "first experiment"): the 90% CI of (B - C)
  lies inside [-0.10, +0.10] (two one-sided tests at 5%).
- **Inconclusive**: anything else. Report it as inconclusive; do not add episodes after
  looking at results.

Secondary reading (descriptive, no decision): if B is close to A in stage 2 and B invented
multiplication in most episodes, an invented and saved multiplication can replace a given
one; if B is close to C, saving alone did not make the invention reusable.

## Sample size justification

With per-episode standard deviation of stage-2 accuracy assumed 0.25, N = 40 per group
gives a standard error of the difference of 0.25 * sqrt(2/40) = 0.056, so the 90% CI half
width is about 0.09, just inside the margin 0.10. If the observed standard deviation is
larger, the result can be inconclusive; this is accepted and reported.

## Budget

- Calls per track: at most 3 groups * 40 episodes * 40 tasks * 3 attempts = 14,400
  (28,800 for both tracks); the expected number is lower (most tasks need 1 attempt).
- Tokens: `python -m atoms_mul.analysis.cost` gives the estimate from the rendered prompts
  of the dry run. The supervisor approves model, price and the exact command before any
  paid call.

## Exclusions

- None by outcome. An attempt that fails because of an API error (including malformed
  responses) is retried up to 3 times with the same seed; a task still failing for API
  reasons is recorded as `api_error` and reported separately. An episode counts for the
  primary stage-2 outcome only if all 24 stage-1 and all 16 stage-2 tasks are recorded,
  and at most 2 of the 16 stage-2 tasks have `api_error`; those tasks are excluded from
  the episode's accuracy denominator. A primary decision requires exactly 40 eligible
  episodes in each of B and C; otherwise the decision is diagnostic with the eligible
  episode counts and no primary verdict.

## Amendments

- 2026-11-05, before any paid run: clarified that an eligible episode records all 40
  tasks, and that 40 eligible episodes in each comparison group are required for
  a primary verdict. Scripted dry runs remain diagnostic.
