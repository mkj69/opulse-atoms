# Experiment 3: open kinds and fraction transfer

K1 may invent operations; K2 may also invent objects; K3 may also invent
combinators; optional K4 also permits bounded laws; K5 adds public-value
observations and K6 adds scoped Pair-to-Frac bridges. All six use the same
integer layer 0, two frozen task sets and
the same library-saving rules. [PREREG.md](PREREG.md) fixes the outcome and
decision rule; [INTERFACE.md](INTERFACE.md) fixes the ASCII learner protocol.
`atoms_kinds.ascii` delegates supported expressions and laws to the shared
notation parser. Its narrow compatibility adapter handles dynamic `Pair<...>`
construction, legacy `@combine` names, and the fraction object's expression
canon, which the core compact declaration format cannot represent.

From the repository root:

```sh
export PYTHONPATH=src:experiments/atoms_kinds:experiments/atoms_mul
python -m pytest -q experiments/atoms_kinds/tests experiments/atoms_mul/tests
python -m atoms_kinds.harness --policy object --groups K1,K2,K3,K4,K5,K6 --episodes 2 --run-id dryrun_object
python -m atoms_kinds.harness --policy operations --groups K1,K2,K3,K4,K5,K6 --episodes 2 --run-id dryrun_operations
python -m atoms_kinds.harness --policy refused --groups K1 --episodes 1 --run-id dryrun_refused
python -m atoms_kinds.harness --policy observation --groups K5 --episodes 1 --run-id dryrun_observation
python -m atoms_kinds.harness --policy bridge --groups K6 --episodes 1 --run-id dryrun_bridge
```

To regenerate committed dry runs, append `--out /tmp/atoms_kinds_regen` to
each command and copy its seven output files to the matching `runs/dryrun_*`
directory. The runner refuses to overwrite an existing run, and `--resume`
rejects changed code or world hashes.

Included `runs/` are offline diagnostics, not model evidence. Each contains
results, complete prompts, episode summaries, bootstrap analysis, a markdown
summary, and an expected/worst-case token estimate (40 episodes per group,
1.5 attempts expected, three attempts worst; chars/4, 1024 maximum output
tokens). No USD estimate is provided without model pricing. The signed-integer
fraction reference is Python's independent `fractions.Fraction`; hidden grading
runs only the Opulse kernel. `Frac` is a sealed refined `Pair` with canonical
numerator and positive denominator; the object dry run promotes it with bounded
evidence over all 156 Pair representations in the recorded -6..6 scope. The K2
and K3 scripts also save reusable `fraction_num` and `fraction_den` helpers over
`Frac`; K3 additionally saves a slot-based `@combine[f]`.
K4 saves `#add_comm` with bounded evidence on 169 integer pairs in -6..6.
Answers are plain programs, not derivations; the law cannot be used as a
`by #add_comm` rewrite step in this experiment. K4-K3 is an optional
secondary diagnostic alongside the frozen K2-K1 and K3-K2 contrasts.
K5-K4 and K6-K5 are descriptive secondary contrasts; observation and bridge
scopes, verification and promotion are reported separately.
K5 reads the public Pair numerator through `Pair.num`, not a truth probe;
public-value observation evidence records non-interference as not applicable.
Refined `Frac` field access canonicalizes valid, noncanonical representations;
invalid bases remain rejected.
Operation-only definitions without a declared reference remain callable and
are charged for their unfolded execution, not promoted on the basis of their
names. Comparisons are diagnostic until 40 complete eligible episodes per
compared arm are available.

Frozen task regeneration for *verification only* (do not overwrite the files
for a real run without a new preregistration):

```sh
python -m atoms_kinds.tasks --out /tmp/atoms_kinds_tasks
```

**Real run: requires supervisor approval; do not run.** After approval, choose
one fixed model and record its input/output price before spending:

```sh
python -m atoms_kinds.harness --policy llm --allow-api --model MODEL_APPROVED_BY_SUPERVISOR --groups K1,K2,K3,K4,K5,K6 --episodes 40 --run-id real
```

Set `OPENAI_API_KEY` before an approved run. Resume interrupted runs with the
identical command plus `--resume`. The checkpoint validates tasks, world hashes,
model, policy and budgets; completed episodes are not rerun. This experiment
imports the `atoms_mul` LLM actor, bootstrap utilities, cost estimator, and
checkpointed shared `kinds` runner. The fraction-specific task loop stays local.

Open limitations: the shared parser cannot express dynamic Pair construction or
the experiment's legacy combinator signature; K1 can compute every task, so a zero
effect cannot show that fraction objects are useless in other domains.
The adapter additionally rejects private sealed access on both answer and
definition paths: the current core object checker only applies its seal check
when checking an object definition, not when checking an operation definition.
The core owner should enforce this centrally; then the local guard can go.
Core 0.4 resolves saved invented-object interfaces, allowing cross-kind
definition towers. Direct task answers using `Frac.make/num/den` also work.
Core law verification and rewrite replay are available; the experiment uses
plain-program answers, not a derivation answer format. The core library currently
does not bind law variables for direct `Library.run` calls, so tests evaluate
the statement and its replayed rewrite instead.
The shared checkpoint runner accepts this track through a small extension hook.

2026-11-05 offline replay amendment: eligibility requires each frozen stage task
ID once per registered episode index 0..39. K5 and K6 report public-value
observation scopes; K6 requires checked commuting pairs and supports partial
`where` domains. Invented pure operation dependencies in observations remain
blocked by the core checker pending spec 0.5 R13-D support.
