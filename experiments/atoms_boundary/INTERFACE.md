# Boundary experiment interface

Decision and eligibility helpers are shared via `atoms_mul.analysis.decision`;
see multiplication INTERFACE section 7. Cost estimates use
`atoms_mul.analysis.cost.estimate`.

- `atoms_boundary.tower.build_tower()` parses `SOURCE` as AML and returns a core
  `Library` with five promoted operation definitions and recorded exhaustive
  evidence. `definitions_text(library)` uses the AML canonical printer and
  core layers; displayed definitions reparse to the exact promoted definitions.
- `atoms_boundary.items.generate_inputs()` deterministically produces 48
  triples in 0..3; `frozen_inputs()` validates `items/frozen.csv`; `items(lib)` returns
  item ids, full kernel traces and boundary-independent answers.
- `atoms_boundary.prompts.boundary_for(id, form)` maps a form (0..2) to a
  boundary (0..2). `render(item, boundary)` returns ASCII-only prompts with
  complete core `flatten_calls` traces (at most 65 calls on the item domain;
  reject anything beyond the registered 120-line bound). `grade(item, reply)`
  accepts exactly `value=N; adds=N`, without extra text, returning independent
  `value_correct` and `adds_correct` booleans.
- `atoms_boundary.run.run(policy, episodes, run_id, out, resume, allow_api, model)`
  writes a config, one atomic form-episode artifact per form/episode, and final
  `results.jsonl`. The shared multiplication harness atomic writer is reused.
  The checkpoint has a config header and one completed form-episode per line;
  resume rejects shrinkage and changed policy, model settings, item/definition
  sources, runner source (including seed logic), boundary assignments, grader
  regex/source, prompt source or rendered prompt bytes. Configuration covers
  everything shown to and graded for the model.
  The shared-pipeline-only refactor retains the archived `tower` and `harness`
  hashes for exactly reviewed source bytes; any subsequent change to either
  source changes the configuration hash and blocks resume.
  `llm` imports the shared opt-in `LLMPolicy` (three internal API retries).
- `atoms_boundary.analysis.analyze(rows)` returns the preregistered value-accuracy
  cluster bootstrap and exclusion decision, with a diagnostic decision until
  40 complete episodes exist (each form 0, 1 and 2 exactly once, all 48 item ids
  exactly once per form at their assigned boundaries), and per-boundary value, add-count,
  and joint accuracy; `cost(rows)` uses the shared cost helper.
  No scripted-policy result is interpreted as a model outcome.
- `atoms_boundary.memo.memo_scope(scope)` returns a core scope with only recursive
  `Rec` binders switched to `memo=True`; when a separately promoted `_memo`
  binder exists, it uses that verified body. The primary tower remains an
  unpromoted diagnostic copy. `compare_runs(plain, memo, args)`
  checks outcome, charged steps and jumps; `work_rows(library)` reports
  `(id, a, b, c, value, steps, plain_work, memo_work)` for the frozen items.
  `python -m atoms_boundary.memo` prints `items/memo_work.csv`. This optional
  diagnostic never changes the primary run, prompts, or analysis.
- `atoms_boundary.pipeline.promote_tower()` runs the same write, check, callable,
  exhaustive verify, account and promote sequence for both towers. The Pascal tower
  additionally promotes `choose_memo` with its own evidence and contract on the same
  45-cell scope; `cost_inputs()` selects the 12 seeded interior
  cells. `cost_rows()` uses `compare_runs`
  with `name="paths"` to check each full outcome and charged step count, then
  reports physical work and memo hits. `python -m atoms_boundary.memo_cost`
  prints `items/memo_pascal_cost.csv`, without adding model prompts or touching
  the primary boundary run.
