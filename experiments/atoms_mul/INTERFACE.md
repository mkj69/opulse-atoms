# atoms_mul: module contracts

Experiment: "Is multiplication innate or invented?" (design doc section "first experiment").
This file is the contract between the modules of `experiments/atoms_mul/`. Every module
must follow it exactly. Change it only through the experiment lead.

The AML interpreter is the experiment's grader; `kernel/core_backend.py` compiles
its definitions to the atoms-v2 kernel (`opulse.atoms.kernel`) for independent
cross-checks. The machine track uses the computer-world runner, with its core
adapter for group A. Both tracks mirror saved definitions into the published
atoms-v2 library. The grader uses exact layer-0 steps; boundaries do not change
execution or outcomes.
The core mirror maps AML `Nat` to core `int` consistently across the mirrored
operation signatures and world operations. Core now accepts bare integer
literals at refined `nat` output edges, but `make_callable` on a `nat` output
still fails with `sample (): unknown kernel node: {'digest':
'28c9d25ad4f22aef191ec7048c0098931fdd6dc18943b7af62ee0da88e75d889',
'host': 'atoms_mul.kernel.ops:nat_valid'}`: the refined sort's given host `valid` rule
is passed to the kernel as a node. The stopgap mapping preserves output checking
(`Bool` cannot satisfy `Nat`) and accepts literal and operation results alike.
The declared world files retain the original refined `nat` sort; the experiment
kernel enforces the 0..10**9 range on operations and AML checks literal ranges
before saving. The mirror does not independently prove that arbitrary integer
literals are in range. Verified mirror scopes are the core library's recorded
`evidence.scope.checked` (size, digest and bounds), not the AML equivalence
check's human-readable scope label or a caller-owned verification request.

## Layout

```
experiments/atoms_mul/
  INTERFACE.md  PREREG.md  README.md
  atoms_mul/__init__.py
  atoms_mul/kernel/      lang.py nodes.py check.py evaluate.py library.py worlds.py equiv.py __init__.py
  atoms_mul/machine/     lang.py check.py compile.py evaluate.py library.py equiv.py env.py
  atoms_mul/tasks/       generate.py reference.py __init__.py
  atoms_mul/harness/     env.py prompts.py policies.py metrics.py run.py __init__.py
  atoms_mul/analysis/    analyze.py cost.py llm_policy.py __init__.py
  worlds/                A.json B.json C.json        (frozen world declarations)
  tasks/                 stage1.json stage2.json     (frozen task files)
  runs/dryrun_*/         committed AML and machine dry-run output
  tests/                 test_atoms_mul_*.py (no conftest.py: it would shadow tests/conftest.py)
```

Import root: `experiments/atoms_mul` (pytest gets it from `pythonpath` in pyproject.toml).
Module commands run as `PYTHONPATH=src:experiments/atoms_mul python -m atoms_mul.<...>`.
Runtime dependencies are the Python standard library and `opulse`; tests additionally use
`pytest` and `hypothesis`. Everything is deterministic: no wall clock,
no unseeded randomness, `random.Random(seed)` only, JSON written with `sort_keys=True,
indent=1, ensure_ascii=False` and a trailing newline.

## 1. Values and outcomes

- A value is a Python `int` (natural number, `0 <= v <= MAX_NAT`, `MAX_NAT = 10**9`) or a
  Python `bool` (only as the result of a test operation). Booleans are never ints:
  `True` is not `1`.
- `Outcome` (frozen dataclasses in `kernel/evaluate.py`):
  - `Ok(value)`
  - `Bottom(reason: str)`: the computation failed (`"overflow"`, `"negative"`,
    `"type: ..."`, `"no such name ..."`).
  - `Unknown(resource: str)`: `"fuel"` (step budget exhausted) or `"depth"` (call depth
    exhausted). `Unknown` is never judged correct, even when two Unknown values have
    the same resource. Graders test `isinstance(outcome, Ok)` before comparing `.value`.

## 2. Worlds (layer 0)

`worlds/<G>.json` and `kernel/worlds.py`:

```json
{"world": "atoms_mul_B", "version": 1,
 "objects": ["nat", "bool"],
 "open_kinds": ["operation"],
 "operations": [{"name": "add", "inputs": ["nat","nat"], "output": "nat",
                 "rule": "a + b", "errors": "overflow if > 1000000000", "cost": 1}, ...],
 "combinators": ["var", "lit", "call", "let", "if", "rec"],
 "observation": "inputs_results_errors_steps",
 "library": true}
```

Operations (every call costs exactly 1 layer-0 step):

| name | inputs | output | rule | error |
|---|---|---|---|---|
| add | nat, nat | nat | a + b | Bottom("overflow") if > MAX_NAT |
| sub | nat, nat | nat | a - b | Bottom("negative") if a < b |
| succ | nat | nat | a + 1 | Bottom("overflow") |
| pred | nat | nat | a - 1 | Bottom("negative") if a = 0 |
| is_zero | nat | bool | a = 0 | none |
| eq | nat, nat | bool | a = b | none |
| lt | nat, nat | bool | a < b | none |
| mul | nat, nat | nat | a * b | Bottom("overflow") (world A only) |

- World A: all eight operations, `library: true`.
- World B: no `mul`, `library: true`.
- World C: no `mul`, `library: false`.
- All three: the same combinators. Literals are natural numbers.

`kernel.worlds.load_world(group: str) -> World` (group in "A","B","C"); `World` has
`.name, .group, .operations: dict[str, OpSpec], .library_enabled: bool, .to_json() -> dict`.
`kernel.worlds.write_worlds(dir)` writes the three frozen JSON files; a test checks that
the committed files equal the generated ones.

## 3. Language (AML, what the learner writes)

### Core ASCII notation comparison

AML keeps its local parser and printer. `opulse.atoms.notation.parse_definition`
handles the typed `Nat`/`Bool` signatures and simple `if`/`let` expressions,
mapping `if` to a single-arm `Case(Test(...), default=...)`; these parts could
convert losslessly to AML `If`. It does not accept the whole learner language:

| Valid AML input | Core `parse_definition` result | Required AML behavior |
|---|---|---|
| `op solve(x: Nat) -> Nat = x` | `expected given or L<n>` | suffix is optional in submissions |
| `op MUL(a: Nat, b: Nat) -> Nat = add(a, b) L1` | `invalid definition name` | uppercase names are valid and used by saved inventions |
| `op f() -> Nat = 0 L1 # note` | `unexpected token` | `#` starts a line comment |
| `op f() -> Nat = 0 L1` followed by `op g() -> Nat = f() L1` | `unexpected token` | multiple definitions and `save` share one program |

Core `print_definition` also always appends `given` or `L<n>`, while AML
`format_def` omits the suffix. Delegating now would change committed learner
prompts and library/listing round trips. Removing comments, splitting programs,
inserting suffixes and remapping uppercase identifiers would amount to keeping
a second lexer/parser. No prompt or frozen artifact is regenerated; retain
`kernel/lang.py` and `kernel/nodes.py` until core supports this AML subset
without changing canonical `format_def` output.

```
program  := (op | save)*
op       := "op" NAME "(" [NAME ":" sort ("," NAME ":" sort)*] ")" "->" sort "=" expr ["L" INT]
sort     := "Nat" | "Bool"
save     := "save" NAME
expr     := INT | NAME | NAME "(" [expr ("," expr)*] ")"
          | "let" NAME "=" expr "in" expr
          | "if" expr "then" expr "else" expr
          | "(" expr ")"
```

- NAME = `[A-Za-z_][A-Za-z0-9_]*`, not a keyword (`op save let in if then else`).
- `def` is rejected with a syntax error showing the `op` form. The optional `L<n>` suffix
  is used by library listings; submitted definitions do not need it.
- INT = decimal natural number without sign. Comments start with `#` and end at line end.
- `if` condition must have sort `Bool`; both branches must have the same sort. The checker
  validates every argument and result sort before evaluation.
  Only the chosen branch is evaluated. A Bottom condition aborts the `if` with
  `Bottom("nan_condition")` (spec 6.1); an Unknown condition aborts it with that Unknown.
- Call targets: world operations, defs in the same program, saved library definitions.
  Recursion and mutual recursion are allowed (combinator `rec`); fuel bounds them.
- Names are unique: a def may not reuse a world operation name, a library name, or another
  def name in the same program. Parameters must be distinct.

Syntax tree (`kernel/nodes.py`, frozen dataclasses): `Var(name)`, `Lit(value)`,
`Call(name, args: tuple)`, `Let(name, bound, body)`, `If(cond, then, other)`;
`Def(name, params: tuple[str, ...], body, param_sorts, result_sort)`; `Program(defs: tuple[Def, ...],
saves: tuple[str, ...])`. Every node has `to_json()` and there is `node_from_json()`;
`format_def(Def) -> str` prints canonical AML that parses back to the same tree.

`size(def) = 1 + len(params) + nodes(body)`, where every `Var`, `Lit`, `Call`, `Let`,
`If` node counts 1. Sort annotations do not count. This is the definition length used by every metric.

## 4. Kernel API (`atoms_mul.kernel`)

```python
parse_program(text: str) -> Program              # raises AmlSyntaxError(message, line, col)
check_program(program, world, library) -> list[str]  # empty list = OK; messages are learner-visible
evaluate(name, args, *, world, program=None, library=None,
         fuel=200_000, max_depth=2_000, boundary=frozenset()) -> Run
```

`check_program` reports: unknown call target; wrong arity; duplicate or shadowing names;
duplicate parameters; unbound variable; argument/result sort mismatch; non-`Bool` if
condition; branches of different sorts; `save` of an unknown name, of `solve`, of a name
already in the library; a saved def that calls an unsaved def of the same program (saves
must be closed under dependency); any `save` when `world.library_enabled` is False
(message: `"saving definitions is not available in this world"`).

`Run` (frozen dataclass): `outcome: Outcome`, `steps: int` (exact layer-0 operation calls,
always counted through every definition, saved or not), `boundary_steps: int` (same run,
but each call of a name in `boundary` counts 1 and its inside counts 0), `calls: dict[str,
int]` (number of calls per defined name, including library names).

Hard rules (each has a test):
1. The outcome never depends on `boundary`; only `boundary_steps` does.
2. A program that uses a saved library definition gives the same outcome and the same
   `steps` as the same program with that definition pasted in as a local def
   (always unfoldable, same result).
3. Fuel counts layer-0 steps. When `steps` would exceed `fuel` the outcome is
   `Unknown("fuel")`; depth beyond `max_depth` gives `Unknown("depth")`. No Python
   `RecursionError` may escape (evaluate iteratively or with an explicit stack guard).
4. Evaluation is deterministic.

### Library (`kernel/library.py`)

```python
@dataclass
class Definition:      # field names follow the atoms-v2 Definition record
    name: str; kind: str = "operation"; origin: str = "invented"; layer: int
    depends_on: tuple[str, ...]; params: tuple[str, ...]; body: dict  # node JSON
    param_sorts: tuple[str, ...]; result_sort: str
    evidence: dict | None   # {"method": "exhaustive", "scope": "...", "seed": None}
    cost: dict              # {"size": int, "length": int}  (length = nodes(body), atoms-v2 cost.length)
    status: str             # "callable" (stored, charged unfolded); "promoted" not used in v1
    created_task: str       # task id where it was saved
class Library:
    def add_from_program(self, program, names, task_id) -> list[Definition]
    def get(self, name) -> Definition | None; def names(self) -> list[str]
    def listing(self) -> str     # canonical AML with L<layer> on each entry, in save order
    def to_json(self) -> list[dict]; @classmethod from_json(cls, data) -> Library
```

`layer` = 1 + max layer of its dependencies (world operations have layer 0).
`depends_on` = direct call targets (operations and definitions), sorted.

### Equivalence (`kernel/equiv.py`)

```python
MUL_DOMAIN = 16   # checks a, b in 0..15
is_mul_equivalent(name, *, world, program=None, library=None) -> dict
  # {"equivalent": bool, "method": "exhaustive", "scope": "a,b in [0,15]", "counterexample": [a,b] | None}
constant_multiplier(name, ...) -> int | None   # unary def equal to k*x on x in 0..63, k in 2..20
```

The check uses `evaluate` (exact interpreter). A pair whose outcome is not `Ok(a*b)`
(including Unknown) makes the definition not equivalent.

## 5. Tasks (`tasks/stage1.json`, `tasks/stage2.json`)

Each file is `{"stage": 1 | 2, "seed": <int>, "generator_version": <int>, "tasks": [Task, ...]}`.
Stage 1 has generator version 2; stage 2 has version 3 and all 16 dot tasks use
variable `(q_i, p_i)` pairs (six 2-pair, five 3-pair, five 4-pair tasks).

```json
{"id": "s1_t03", "stage": 1, "family": "constant_scale" | "variable_scale" | "compound" | "dot",
 "statement": "learner-facing text",
 "params": ["x"], "solve_signature": "solve(x)",
 "public_examples": [{"args": [3], "expected": 24}, ...],    # 3 examples, shown
 "hidden_tests":    [{"args": [17], "expected": 136}, ...],  # 12 tests, never shown
 "reference_aml": "op solve(x: Nat) -> Nat = mul(8, x)"}   # world-A reference program
```

- No statement may contain (case-insensitive) `mul`, `multipl`, `times`, `product`,
  `twice`, `double`, `triple`, `*`, `\u00d7`, `\u00b7`. A test enforces this list.
- `expected` comes from `tasks/reference.py` (plain Python); a test checks that running
  `reference_aml` in world A through the kernel gives the same values for every example.
- Inputs are small enough that all expected values are `<= 10**6` and a repeated-addition
  solution stays within the default fuel.

## 6. Harness (`atoms_mul.harness`)

Policy protocol:

```python
class Policy:
    name: str
    def reset(self, *, group: str, episode: int, seed: int) -> None
    def act(self, observation: dict) -> str     # returns AML program text
```

Observation: `{"group", "episode", "stage", "task_id", "attempt" (1-based),
"library_enabled" (bool), "prompt" (full text the model sees), "task" (statement,
params, public_examples),
"library" (listing text or ""), "feedback" (list of previous attempt feedback strings)}`.

Episode = one pass over all stage-1 tasks in a seeded order, then all stage-2 tasks in a
seeded order. Episode `i` uses order seed `1000 + i` for every group (same order across
groups). The model sampling seed instead adds group offsets (A: 0, B: 100000,
C: 200000) to `1000 + i`. Up to `MAX_ATTEMPTS = 3` attempts per task. Feedback after a failed attempt:
syntax/check errors, or for each public example the outcome and steps followed by "at
least one hidden test failed". Hidden tests are never shown. An exception from the `llm`
policy (after its own 3 retries, including malformed responses) ends the task with `api_error: true`.
The two tracks use one episode runner for ordering, retries, feedback lifecycle,
final-attempt saving, mirror calls, and record assembly. Track adapters supply parsing,
checking, hidden-test grading, prompt rendering, equivalence, and library accounting.
`mul_equivalent` never counts a definition whose call graph reaches the given `mul`
operation (world A wrappers are not inventions). A task is correct when every hidden test gives `Ok(expected)`.

After the final attempt of a task, the `save` lines of that final attempt are applied to
the library (groups A and B only, only if the program passes `check_program`). Saving is
independent of correctness.

Results: `runs/<run_id>/results.jsonl`, one record per (group, episode, task):

```json
{"run_id", "policy", "group", "episode", "order_seed", "stage", "task_id", "family",
 "attempts": int, "correct": bool, "final_program": str,
 "defs_written": [{"name", "size"}], "length": int,        # sum of sizes of defs in final program
 "saved": [names], "library_size_after": int,
 "uses_library": bool,         # final solve reaches a library definition saved in an earlier task
 "library_calls": int,         # dynamic calls to library definitions over hidden tests
 "steps": int | null,          # layer-0 steps summed over hidden tests (null if any not Ok)
 "boundary_steps": int | null, # library definitions as one step
 "mul_equivalent": [names],    # defs in final program or saved by it that pass is_mul_equivalent
 "core_library": [{"name", "status", "problems", "evidence", "contract", "cost"}],
 # Each saved definition records its core pipeline status and problems. Evidence includes
 # verification method, scope and checks (null before verification); contract is null
 # before promotion; cost includes length, steps and reuse (steps may be null).
 "check_errors": int}          # attempts that failed parse/check
```

and `runs/<run_id>/summary.json` with per group and stage: accuracy, mean attempts,
mean length, total length including definition cost (each saved definition's size counted
once in the task where it was written; length of library entries is not charged again),
mean steps, episodes with a mul-equivalent definition, reuse rate (share of tasks with
`uses_library`), and `config` (policy, groups, episodes, max attempts, fuel, task and
world declaration hashes; machine group A also hashes the derived `computer_a` declaration).
A checkpoint `episodes.jsonl` starts with a config header, and resume
rejects mismatched policy, model, fuel, max attempts or task/world hashes; groups and
episodes may only grow. Final artifacts are atomically replaced before checkpoint removal.
An unterminated trailing checkpoint row is discarded and rerun; a malformed complete
row, including one in the middle, is rejected without dropping later rows.
An episode is reusable only with one result per frozen task (24 stage-1 and 16
stage-2 records), the documented result fields, and one captured prompt for
every attempt of every task.
Incomplete episodes are rerun; complete checkpoint rows are preserved. When no
checkpoint remains, resume reconstructs finished pairs from final artifacts
using the same completeness checks; if any final artifact is missing, it reruns
the episodes rather than trusting the partial artifacts.

## 7. Analysis (`atoms_mul.analysis`)

`analyze.py --run runs/<id>` reads `results.jsonl`, applies PREREG.md exactly and writes
`analysis.json` and `analysis.md`. `cost.py` renders every prompt of a dry run, counts
characters, and prints an estimate of calls and tokens (chars / 4) for a real run.
`llm_policy.py` holds the real-model policy; it refuses to run unless `--allow-api` is
given and is never called by tests or the dry run.

`decision.py` is the shared analysis API for multiplication, boundary, and bridge:
`bootstrap_difference`, `bootstrap_median_ratio` (optional `include_90`),
`intervals`, `complete_ids`, `require_complete`, `difference_decision`, and
`ratio_decision`. It fixes the bootstrap seed and percentile interpolation;
each experiment supplies its pre-registered margins, outcomes, episode
eligibility, and decision labels. Boundary uses strict equivalence bounds;
multiplication uses inclusive ones. `cost.estimate` is already the shared
cost estimator; bridge uses the multiplication harness checkpoint/fingerprint
implementation, while boundary fingerprints its own per-form prompts and
runner source because its resume artifact format differs.

## 8. Machine track

The parallel machine experiment uses `atoms_mul.machine` and the frozen
`tasks/machine_stage{1,2}.json` (seeds 111 and 222). A is `computer_a` with the given
`mul` state transition; B and C use `computer@1` without `mul`; only C disables
cross-task saving. It uses the same stage counts, metrics, preregistered analysis,
result schema, checkpoint/resume, atomic artifacts, API-key validation, and prompt
capture as AML; both tracks put `"track"` in config, results, and prompts.
Machine-specific grading and public feedback remain in the machine adapter; the
shared runner does not change the final-`r0` projection or MASM prompt text.
Machine tasks use generator version 2, 1-based IDs, byte values 0..255, and counts
0..20; at least six hidden tests per task wrap modulo 256. Run
`PYTHONPATH=src:experiments/atoms_mul python -m atoms_mul.harness.run --track machine --policy inventor --groups A,B,C --episodes 2 --run-id dryrun_machine_inventor`.
The `--track aml` default retains the AML command. A real `--policy llm` run on
either track requires supervisor approval; do not run it.

MASM has `sub main:` as its entry point and `end` after each subroutine; `save NAME`
persists a definition in A and B after the final valid attempt. An instruction or
label line each contributes one to `size(sub)` (the `sub` and `end` delimiters do not).
Registers are `r0`..`r3`; byte literals and memory addresses range 0..255. `set`,
`add`, `dec`, `load`, `store`, `mul` (A only), and the `is_zero` test in conditional jumps each cost one layer-0
step; calls cost the exact steps of their unfolded subroutine. An executed `jmp`,
`jz`, or `jnz` costs one jump step, and conditional jumps also cost one `is_zero`
step. Falling through into a label compiles to a Jump, costing one jump step.
Falling off the end halts. `halt` returns the current state. The judge projects
only final `r0`; other state changes do not affect task correctness, but a saved
definition's boundary never changes its execution, outcome, or unfolded step count.
The equivalence check exhaustively projects `r0` over r1,r2 in [0,15], and the
offline full check covers all 65,536 pairs. Neither implies full-state equivalence.
The full-domain check uses a no-trace execution path for instruction-only Blocks;
unsupported bodies fall back to the world runner.
Machine library JSON retains the canonical MASM source, so round-tripping a
saved definition preserves its learner-visible listing.

MASM B/C executes with `opulse.worlds_v2.computer.runner.run`, which accepts
`Test` in `CondJump`, traces jumps and failed atoms, and reports the last state.
A uses `kernel_scope.scope` plus the given `computer_a` `mul` atom in the atoms
kernel: the standalone world runner exposes only B's instruction set. The
kernel trace provides exact layer-0 and boundary costs for A; neither path
changes its execution or fuel when a saved subroutine becomes visible as one step.
The duplicated experiment interpreter has been removed.

## 9. Core library mirror

`atoms_mul.kernel.core_library` describes A, B and C as `opulse.world/2` declarations
in `worlds/decl/`. `load_decl(group)` loads a `WorldDecl`; `atoms(group)` binds its
layer-0 operations to `kernel/ops.py`, the single source of the operation semantics
that the AML evaluator also uses. Every host digest is the sha256 of `ops.py`; after
editing it, run `core_library.write_decls()` (a test checks the committed files). The experiment's `evaluate` remains the grader.
The cross-check in `kernel/core_backend.py` uses separately implemented Python
arithmetic and comparisons for its layer-0 atoms; using the grader's `ops.py`
there would let a wrong shared atom pass unnoticed. The `core_library` hosts
continue using `ops.py` to preserve their declaration digests. The independent
atoms are used only by the cross-check.
`open_kinds` contains only `operation`, so the core library rejects invented objects,
combinators, and observations in these experiment worlds. Each declaration is refreshed
with `core_library.write_decls()`.
The AML mirror does not use memoized recursion; the core `Run.steps` retains the plain
layer-0 step count, with no memoized-work adjustment required for this track.
The in-memory mirror retains `int` edges for `Nat` because core still infers
`Lit(0)` as `int` and rejects literal-only bodies with refined `nat` outputs.
It rejects a `Bool` body declared `Nat`; persisted declarations and frozen
world hashes remain unchanged.

`compile_definition(entry, lookup)` translates saved AML definitions into core
operation definitions. Direct self-calls are enclosed by `Rec(measure="fuel")`;
other calls remain named dependencies. Mutual recursion is not representable in
atoms-v2/0.2 as a single `Rec`: compilation returns `None`, and mirroring reports
`mutual recursion is not representable in atoms-v2/0.2` without storing a broken
definition.

`CoreMirror(group).mirror(entries)` accepts save-order AML library entries, optionally
wrapped as `{"definition": entry, "mul_equivalent": true}`. Each entry is written,
checked and made callable using four fixed arity-matched samples. The core library
stores callable definitions even without equivalence evidence. Every callable save
is accounted over its samples; a marked multiplication candidate is verified against
`a * b` exhaustively on `a, b in 0..15`, re-accounted over that scope and
promoted only when core verification succeeds. Verification failures remain callable
and return a counterexample in `problems`; per-entry results include core status,
evidence and cost. Accounting callable saves does not invent verification
evidence. `derived_world()` exposes promoted definitions, scopes and contracts;
it never changes layer-0 steps. An AML entry's local `evidence` field cannot
trigger core verification or promote a definition: only an explicitly marked
candidate verified by the core library receives a recorded checked scope.

## 10. Machine core mirror

`atoms_mul.machine.core_library` loads `worlds/decl/computer@1.json` for B/C;
A extends it with the given `computer_a` `mul` instruction. Saved MASM operations
compile to core `Definition`s on `machine_state` with their original `Blocks`
bodies and dependency layers. Every entry passes through `write`, `check`,
`make_callable`, and `account`. The host-State scope subclass is removed because
core `Library.scope()` now handles record-shaped compose objects and retains
the host-State machine instructions.

The experiment's `r0` equivalence flag only *requests* exhaustive core
verification over r1/r2 in 0..15, other fields zero (256 states). The reference
is the **full state** produced by `machine.given_mul`, not its r0 projection.
Core evidence records the exact checked state tuples by digest and size;
the projection's human-readable range label is not promotion evidence.
If a candidate changes any other register or flag, it remains callable with no
verification evidence, and its `core_library[].problems` records a compact
counterexample. Successful full-state verification re-accounts costs and promotes
with the verified scope and contract; no projection evidence is upgraded.
Group C cannot save. Task grading always uses the experiment evaluator.
