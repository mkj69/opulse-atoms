# Generator developer guide

`opulse.gen_v2` proposes invented objects, operations, combinators, observations,
laws and bridges,
then admits each through the `opulse.atoms` write, check, callable, verify, account,
promote pipeline. A promoted definition retains its scope and contract and can be
unfolded to given (layer-0) atoms. This package is not the older
`opulse.generation` operator generator. Laws and bridges are admitted core
definitions with core verification; a promoted equation law supports scoped
rewrite replay. Templates remain generator family metadata: the core has a
`TemplateSpec` record but no template checker, verifier or callable semantics.

Read `docs/spec/atoms-v2.md` sections 8-11 for the definition record, pipeline,
boundaries and invariants. Follow the shared `common.md` rules: worlds decide
which kinds are open, only independent evidence supports an external reference,
and promotion must carry a scope and contract. The generator prints ASCII
notation: `A1<...>`, `f1(...)`, `@k1[f1](...)`, `?q1{...}`; law and bridge
records print `#name` and `~name`. The notation is copyable; do not introduce
Unicode sigils. Check claims at their recorded scope, not on a few illustrative
examples. `tests/gen_v2/test_gen_properties.py` exercises the four invariants
and `audit.audit` replays admitted verification requests.

Generator promotion rule (board 11-05): a generated observation with
`reference: none` in its evidence scope has no independent oracle. It may
promote on `dependency`, `facts_unchanged`, `non_interference` and
`unfold_equivalence` checks instead of the core's `reference` obligation.
No `reference` check is invented. Laws require the core's `holds` check;
bridges require `commutes` and `total_on_domain`. This is pending a core
promotion-policy decision.
Template family records are exported as metadata, not core definitions: core
provides `TemplateSpec` but has no checker, verifier or callable family semantics.
Instances carry their template identity and digest in metadata; listing a
template in `depends_on` requires a core template pipeline and dependency rule.

## Architecture

Core request pending: `Library.run` refuses calls to sealed-object private
accessors, but `Library.scope` is a trusted scope and exposes those accessors
to direct `kernel.call`. Generator admission blocks definitions that read them;
it cannot make arbitrary external callers of the core scope obey the interface.
The core needs a separate public scope and trusted implementation scope before
exports or consumers can safely receive an executable scope for sealed objects.

`GenWorld` describes one typed world and its probe domains. A seeded move emits
a `Candidate`, `admit` checks and runs it through `GenLibrary`, and the resulting
`Entry` becomes available to subsequent moves. Kind hooks implement the extra
obligations for objects, combinators and observations. `run.generate` schedules
moves; `audit`, curation and export consume the same state. The tables name the
module's principal public entry points and the invariant it protects.

| Module | Main entry points | Responsibility and protected invariant |
| --- | --- | --- |
| `base.py` | `GenWorld`, `Sort`, `Signature`, `Candidate`, `Entry`, `GenState`, `Names`, `Move` | Typed domains, sort finiteness, inventory, requests and unique ASCII names. |
| `library.py` | `GenLibrary`, `scope`, `check`, `record_evidence`, `verify`, `promote` | Cached scope and content/world-hash-bound evidence; checks and promotion still use the core library. |
| `fast.py` | `deep`, `evaluate`, `call`, `promoted_names` | Deep-stack generation without per-call thread hops; only cache explicitly eligible pure definitions. |
| `admit.py` | `admit`, `domain_request`, `run_on_domain`, `KindHook`, `register_hook` | Atomic admission, finite-scope certification and recorded rejection stages. |
| `interest.py` | `fingerprint`, `degenerate`, `score_entries` | Reject equivalent or uninformative proposals before expensive verification; rank survivors. |
| `curate.py` | `curate`, `featured`, `showcase`, `graph_stats`, `dedup_report` | Select diverse entries while including their dependency closure. |
| `audit.py` | `audit`, `AuditReport` | Replay exact requests and check unfolding, boundaries, observation non-interference and evidence. |
| `codec.py` | `encode_value`, `encode_outcome`, `encode_checkpoint_value`, `require_restorable` | Preserve FnRef, cards and host-bool identity; refuse non-restorable checkpoint values. |
| `vocab.py` | `less`, `equal`, `zero_test`, `deciders`, `steps`, `combiners`, `int_measures` | Discover roles by typed probe behavior rather than world-specific operation names. |
| `run.py` | `generate`, `save`, `load`, `RunState` | Deterministic attempts and quotas; resume only with the same seed and world hash. |
| `__main__.py` | `main` | World selection, CLI generation and full/compact/JSONL/Markdown output. |
| `batch.py` | `run_world`, `meets_target`, `publish`, `main` | Per-world configs, audit-before-publish, blocker reports and an index. |
| `configs.py` | `available_adapters`, `WORLDS` | Target, quota, time limit and seed per configured adapter. |
| `export.py` | `export`, `export_compact`, `export_jsonl`, `export_story`, `export_summary_md` | Recheck world hash; export evidence, contracts, examples, tokens and optional traces. |
| `notation.py` | `print_node`, `print_declaration`, `parse_term`, `parse_declaration`, `tokens` | ASCII round trips and token text that concatenates to the printed declaration. |
| `laws.py` | `conjecture`, `check`, `discover`, `admit_discovered` | Propose scoped equations and admit them as core `LawSpec` records with core verification. |
| `bridges.py` | `check`, `propose`, `admit_proposed`, `BridgeRecord` | Propose finite-scope diagrams and admit them as core `BridgeSpec` records with core verification. |
| `templates.py` | `invent_template`, `instantiate_template`, `template_candidate` | Check a recorded family and send each instance through normal admission. |
| `legacy_import.py` | `import_world`, `import_report`, `encode_published_value` | Import published legacy-v1 definitions with a private, validated filter bypass. |

| Subpackage | Main entry points | Responsibility and protected invariant |
| --- | --- | --- |
| `moves/registry.py` | `discover_moves` | Discover `MOVES`, group by kind and reject unknown kinds; the runner then selects open kinds. |
| `moves/operation.py` | `MOVES` | Typed substitution, specialization, composition, branches and recursion. |
| `moves/object.py` | `MOVES` | Compose/refine/constant sorts with constructors and probe witnesses. |
| `moves/combinator.py` | `MOVES` | Typed operation-slot families and callable combinator bodies. |
| `moves/observation.py` | `MOVES` | Probe-only, truth-safe and memory-bearing observations. |
| `moves/modes.py` | `MOVES` | Derived modes (fold, stable iteration, memo recursion, turns) subject to ordinary admission. |
| `moves/templates.py` | `MOVES` | Family instantiations for each supported definition kind. |
| `kinds/objects.py` | `object_atoms`, `sealed_violation`, registered hook | Generate object interfaces; check finite witnesses, canon and sealed reads at admission. |
| `kinds/combinators.py` | `family_request`, registered hook | Verify operation-slot substitutions across the recorded family and input prefix. |
| `kinds/observations.py` | registered hook `check`, `run`, `verify` | Restrict reads and check truth preservation, probe indistinguishability and memory histories. |
| `worlds/_common.py`, `worlds/_catalogue.py` | `build`, `signatures`, `ordered`, `catalogue` | Convert declarations/host atoms into bounded typed probes and truthful tags. |
| `worlds/toy.py`, `worlds/toy_truth.py` | `gen_world` | Small deterministic fixtures for generated values and truth histories. |
| `worlds/classic.py` | `gen_world(name)` | Legacy-v1 adapter for named published worlds, with operation-only admission. |
| `worlds/<name>.py` | `gen_world` | Per-world declarations, atoms, canonical probes, optional truth and measures; see `worlds/lists.py`. |

## Admission and evidence

`admit(state, candidate)` returns an `Entry` or `Rejection(move, kind, stage,
reason)`. Its order matters:

1. Reject `closed_kind` if the declaration does not open the kind (this early
   return is **not** appended to `state.rejections`). Refuse name collisions as
   `check`, without replacing existing atoms, sorts or signatures.
2. Temporarily add candidate atoms and sorts; write, type/kind check and reject
   sealed-sort non-interface reads (`check`). Failed candidates roll back their
   temporary additions. The definition layer is one plus the highest invented
   dependency layer; `depends_on` must match its references.
3. Build a `VerifyRequest`: `domain_request` chooses `exhaustive` only when all
   input sorts certify complete finite universes **and** their entire product is
   covered. Otherwise `bounded` describes the entire size-ordered probe product
   or an equal-size prefix per argument. Hooks downgrade unsupported exhaustive
   object/observation claims to bounded. Invalid/missing scopes or unauthenticated
   references fail `verify`.
4. Run the candidate on that domain, via a kind hook where registered. A run
   exception or `Unknown` on any checked input fails `callable`. A mean layer-0
   step count above `GenWorld.max_steps` fails `cost`.
5. Compute behavioral fingerprints and reject constants, identities, all-failure
   bodies and other uninformative results as `degenerate`; equal behavior is
   `duplicate`. These filters run **before** verification. The legacy importer's
   private keep token may retain a published operator with its filter verdict;
   ordinary candidate metadata cannot bypass the filters.
6. Check kind-specific obligations or use the core operation verifier; failures
   are `verify`. Generated operations without an independent oracle verify
   unfolding only, with `reference: none` in scope (not a fabricated reference
   check). Record evidence, account length and layer-0 steps, then promote with
   a contract. Any pipeline failure is `verify`.
7. Store the entry, behavior fingerprint and **exact** request in
   `state.requests[name]`, increment dependency reuse, and leave the definition
   promoted. An external given-atom reference may support a `reference` check;
   a callable oracle requires declared oracle/table provenance. Self-references,
   same-body aliases and arbitrary invented references do not qualify.

The exact rejection stages are `closed_kind`, `check`, `callable`, `cost`,
`degenerate`, `duplicate` and `verify` (`base.Rejection`, `admit.admit`). A move
returning `None` counts as an attempt, not a rejection. A `Bottom` is a defined
outcome, not an `Unknown` to silently drop.

| Do not weaken this rule | Regression test |
| --- | --- |
| Closed kinds cannot be invented; sealed internals are not read by external definitions. | `test_gen_admit.py::test_admit_rejects_identity_duplicate_and_closed_kind`, `test_gen_admit.py::test_sealed_sort_inside_is_refused_outside_its_interface` |
| A claimed exhaustive domain covers a certified finite sort's full product, not a sample or scattered values. | `test_gen_review_fixes.py::test_exhaustive_claim_must_cover_the_full_probe_domain`, `test_gen_review_fixes.py::test_review4_2_unbounded_probes_are_bounded`, `test_gen_combinators.py::test_bounded_combinator_domain_is_complete_prefix_and_rejects_scattered_values` |
| No independent reference claim for unfolding, aliases, or provenance-free callables. | `test_gen_review_fixes.py::test_generated_operation_claims_no_independent_reference`, `test_gen_review_fixes.py::test_review4_3_self_and_aliased_references_are_not_independent`, `test_gen_review_fixes.py::test_review4_3_oracle_origin_is_required_for_reference_evidence` |
| `Unknown` never passes callable checks; sampled evidence never promotes. | `test_gen_invariants.py::test_audit_admitted_operations_and_seeded_sample`, `test_gen_review_fixes.py::test_review4_2_direct_library_cannot_spoof_exhaustive_scope` |
| Input/output/state and layer-0 steps agree with unfolding under different boundaries. | `test_gen_properties.py::test_i1_named_calls_unfold_on_recorded_inputs`, `test_gen_properties.py::test_i2_boundaries_only_change_visibility` |
| Observation probes do not mutate truth or reveal a hidden distinction by arbitrary reads. | `test_gen_properties.py::test_i3_observing_never_changes_truth_or_hidden_facts`, `test_gen_observations.py::test_grant_act_hidden_truth_and_init_are_rejected` |
| A promoted record has a valid world/content hash, scope and contract; exact requests survive checkpoint replay. | `test_gen_properties.py::test_i4_promoted_content_identity`, `test_gen_review_fixes.py::test_world_changed_in_place_resets_evidence`, `test_gen_review_fixes.py::test_review4_17_checkpoint_restores_exact_requests` |
| Host values that cannot be reconstructed must not enter checkpoints; exports recheck the world hash. | `test_gen_review_fixes.py::test_review4_18_display_only_host_values_cannot_be_checkpointed`, `test_gen_review_fixes.py::test_review4_6_export_rechecks_the_original_world_hash` |
| Do not cache impure given atoms or conceal mutation of probe inputs. | `test_gen_review_fixes.py::test_review4_11_mutating_atom_is_rejected_without_touching_probe_inputs`, `test_gen_review_fixes.py::test_review4_15_uncached_calls_reexecute_impure_atoms_and_cache_hits_do_no_work` |

## Extending the generator

**World adapter:** Start with `worlds/toy.py` or `worlds/lists.py`. Implement
`gen_world()` returning `GenWorld`: a `WorldDecl`, layer-0 `kernel.Atom`s,
typed `Signature`s, canonical `Sort.values` in size order, `open_kinds`, and
optional measures/bases and truth states/probes. Set `Sort.finite=True` only
when values cover the declared universe. For catalogue worlds `worlds/_common.py`
`build` supplies tags, sample caps and derived probe signatures. Keep
observation truth sealed and grant only learner-visible probes. Check the
adapter with `test_gen_worlds.py` and run its audit before publishing.

**Move:** Add a module under `moves/` exposing `MOVES`; each move has `kind`,
`name` and `__call__(state, rng) -> Candidate | None`. Use `state.names.fresh`,
typed signatures and `vocab` behavior rather than hard-coded world operation
names. Set the layer from dependencies and provide the exact spec/body, probe
request, and extra object atoms/sorts if applicable. Keep selection reproducible
given `rng`; `moves/registry.py` discovers the module automatically. Run the
appropriate kind tests and `test_gen_run.py`.

**Kind hook:** Implement `KindHook(check=..., run=..., verify=...)` in `kinds/`
and register it by kind with `register_hook`. `check(defn, lib)` returns type
problems; `run(state, candidate, request)` returns `(args, outcome, steps)` for
the declared domain; `verify(state, candidate, request, results)` returns
`(checks, problems)`. Do not mark a reference check without an independent
reference. `admit` calls `mark_callable` and `record_evidence` for hooked kinds.
Test negative cases, scoped evidence and audit replay, not just acceptance.

## Commands and checkpoints

Run from the repository root with `PYTHONPATH=src`. These are commands actually
run for this guide; the CLI may stop before its target if the move pool or a
time/attempt limit is reached. The `lists` CLI command is a single-world export,
not the batch audit/publish path:

```sh
PYTHONPATH=src python -m opulse.gen_v2 run --world lists --target 300 --seed 1 --out /tmp/gen_docs_lists_cli
PYTHONPATH=src python -m opulse.gen_v2 run --world toy --target 300 --seed 1 --per-kind-min 50 --layer-target 10 --time-limit 120 --out /tmp/gen_docs_cli
PYTHONPATH=src python -m opulse.gen_v2.batch --worlds lists --quick --out /tmp/gen_docs_batch
PYTHONPATH=src python -m opulse.gen_v2.batch --worlds lists --report --out /tmp/gen_docs_batch
PYTHONPATH=src python -m pytest -q tests/gen_v2
```

The quick batch output in this run was
`lists: 8 admitted, L3, 0.4s, 0 audit failures` and its report row was
`lists | 5/0/0/3 | 3/0/0/1 | 0 | 9 | 0 | yes | none`.
The lists CLI reported `300 admitted, 10 max layer, 960 attempts` with
`110` objects, `81` operations, `57` combinators and `52` observations;
its `rejections_summary.stage` reported `4` check, `27` verify,
`111` degenerate and `230` duplicate. The toy CLI reported
`300 admitted, 12 max layer, 526 attempts`; its lack of truth/probes means
that no observation moves ran despite that kind being open.
In a separate measured lists run (`target=60`, `seed=1`,
`per_kind_min=5`, `layer_target=3`, `time_limit=30`), generation took
`3.6s` for `60` admissions in `206` attempts. The four kind counts were
object `22`, operation `18`, combinator `12`, observation `8`; their maximum
layers were `4`, `6`, `4`, `5`. Rejections by stage and kind were
`degenerate`: operation `7`, observation `9`; `duplicate`: object `8`,
operation `1`, combinator `8`, observation `9`; `verify`: combinator `1`,
observation `8`. The most frequent concrete reasons were
`obs.memory / duplicate / same behaviour as q7` (`6`) and
`obs.compose / verify / duplicate: same truth partition as q17` (`6`).
`--quick` publishes partial audited results; without it, unmet quotas write
a blocker record instead of a published dataset. Use `run.save(state, path)`
and `run.load(world, path)` for `opulse.gen-v2.checkpoint/1`, then resume with
`generate(world, target, seed, state=loaded)`. Checkpoints retain attempts,
move statistics, definitions and `state.requests`; a changed world hash, seed,
or un-restorable host value prevents safe replay. Exports are not checkpoints.
`batch --checkpoints DIR` also saves each finished run state as `DIR/<slug>.json`
so a later export change can re-export without regenerating; a state holding
display-only legacy host values (classic action) is skipped with a printed note.

Published records carry the core spec dict plus `spec.tag_order`: the JSON files
are written with sorted keys, and an object's tag order decides its fold handler
order, so a reader rebuilding an object must take the tags in `tag_order`.
Publication marks up to five diverse curated records per kind as `featured`,
with the measured reason in `interest.featured_why`.

## Export samples

The following **shortened** records were taken from the toy CLI run with seed
`1` and target `300` (`/tmp/gen_docs_cli`). For laws, bridges and stories a
separate toy run called `generate(toy.gen_world(), 40, 1,
per_kind_min=0, layer_target=0, time_limit=30)` and then `laws.discover`,
`bridges.propose` and `export_story`; it admitted `40` entries, found `11`
local laws and `27` bridges. Selected fields shown below retain their actual
values; omitted fields are not claims about the full JSON shape.

| Artifact | Actual excerpt | Interpretation |
| --- | --- | --- |
| Full `toy.json` | `"schema":"opulse.gen_v2/1","seed":1,"world":"toy"` | Selected actual fields; `entries` carry body trees, specs, evidence, contracts, costs and examples. |
| Compact `toy.compact.json` | `{"name":"k105","kind":"combinator","layer":1,"display":"@k105"}` | An entry's display fields; body/spec omitted. |
| Dataset `toy.jsonl` | `{"name":"k105","kind":"combinator","layer":1}` | Fields selected from its first complete JSONL entry; one entry per line. |
| `laws.export_json(laws.discover(state, seed=1), state)` | `{"schema":"opulse.gen_v2.law/1","laws":[{"name":"l1","kind":"law","layer":2,"vars":[["a","int"],["b","int"]]}]}` | Selected fields from the first toy law; a generator record, not a core definition. |
| `bridges.to_json(bridges.propose(state, seed=1))` | `{"schema":"opulse.gen_v2.bridge/1","bridges":[{"name":"b1","layer":2,"closed":true,"source":["toy","B1"],"target":["toy","int"]}]}` | Selected fields from the first toy translation. |
| `export_story(state, ["B1"])` | `{"name":"B1","kind":"object","layer":1,"status":"promoted","symbol":"B1"}` | Selected fields from the toy story; its first example is `B1<none:>` with `0` steps and a `trace`. |
| Tokens on `toy.json` entry `f286` | `[{"given":false,"kind":"keyword","text":"op"},{"given":false,"kind":"punct","text":" "},{"given":false,"kind":"operation","layer":1,"name":"f286","text":"f286"}]` | Start of `tokens`; concatenated token text equals the `ascii` declaration. |

The toy summary `toy.md` begins `# toy generator summary` and lists
`object: 113`, `operation: 101`, `combinator: 86`, `observation: 0`.
`export_story(state, [name])` supplies trace examples in memory; batch
`publish` embeds selected stories and separate `*.laws.json` and
`*.bridges.json` files alongside the compact JSON, and checks audit first.
The quick lists batch actually wrote `{"laws":[],"schema":"opulse.gen_v2.law/1"}`;
an empty file is not evidence that the toy law was admitted.

## Known limits and requests

- The board request at `BOARD.md` (11-04, generator code review finding 8)
  reports that the admission-time sealed-sort check does **not** stop a direct
  kernel call to a non-interface accessor. Core needs call-resolution sealing
  if it intends a capability guarantee for learners and tasks.
- The generator's 11-05 board request notes that core currently derives
  observation dependencies from the body, not `memory.init` or `memory.step`.
  Generator moves work around this; core needs these references in dependency,
  layer and content-hash validation.
- Core now verifies admitted `LawSpec` and `BridgeSpec` definitions and replays
  promoted laws as scoped rewrites. Generator-side records are only proposals;
  `TemplateRecord` remains metadata until core verifies template families.
- The generator's action-world board request (11-04) describes limited probe
  diversity and state variety: its observation yield is constrained by the
  available visible probes, not by a permission to read hidden truth.
