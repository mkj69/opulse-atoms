# Boundary visibility experiment

Run from repository root (`pytest` already adds both experiment packages to
its Python path). In a shell set `PYTHONPATH=src:experiments/atoms_mul:experiments/atoms_boundary`.

```sh
python -m atoms_boundary.run --policy oracle --run-id dryrun_oracle
python -m atoms_boundary.run --policy miscount --run-id dryrun_miscount
python -m atoms_boundary.run --policy topline --run-id dryrun_topline
python -m atoms_boundary.analysis --run experiments/atoms_boundary/runs/dryrun_oracle
python -m atoms_boundary.analysis --run experiments/atoms_boundary/runs/dryrun_miscount
python -m atoms_boundary.analysis --run experiments/atoms_boundary/runs/dryrun_topline
```

Scripted policies are diagnostics: oracle computes exact values and counts,
topline computes the value from the top call without reading the trace but
guesses zero adds, miscount shifts the exact add count by one. Value accuracy
is the primary B0-versus-B2 outcome; add-count and joint accuracy are reported
descriptively. The tower is parsed from one AML ASCII source and printed with
the shared canonical printer. Use `--resume`
with identical configuration after interruption.
The 48 frozen triples use inputs in 0..3, so all traces are complete (max
1/5/65 visible calls at B0/B1/B2; the 120-line bound never truncates). A
one-episode dry run reports `diagnostic (n=1 episodes < 40 pre-registered)`;
only a run with 40 complete three-form episodes may receive a confirmatory decision.

**Requires supervisor approval; do not run:**

```sh
python -m atoms_boundary.run --policy llm --allow-api --model MODEL_APPROVED_BY_SUPERVISOR --episodes 40 --run-id real
```

Read [PREREG.md](PREREG.md) before changing item seeds, answers, traces,
decision rules, or any budget parameter.

The pre-registered descriptive memo cost view has no model prompts and does
not enter the primary B0-versus-B2 analysis. Reproduce its per-item snapshot
without changing `runs/`:

```sh
python -m atoms_boundary.memo
```

Its output matches `items/memo_work.csv`. `steps` counts plain layer-0
unfolding; `plain_work` and `memo_work` count actual work. The fixed AML tower
has no repeated recursive subcalls within a `mul` invocation, so memo work
equals plain work for every frozen item. Memo tables do not persist between
separate `mul` calls or score items.

The separate descriptive Pascal cost set tests actual overlapping recursion,
without introducing prompts or changing the primary tower:

```sh
python -m atoms_boundary.memo_cost
```

Its 12 seeded rows reproduce `items/memo_pascal_cost.csv`. `paths(n, k)` and
its recursively defined `choose(n, k)` are parsed from one AML source and
promoted on recorded scopes (45 recursive cells, 12 cost items). The separately
promoted `choose_memo` carries its own 45-cell evidence and contract; cost runs
select that verified memo binder. Both variants return the same outcomes and
charge identical plain unfolding steps, while `memo_work` measures reduced
physical work and `memo_hits` counts actual cache hits.
