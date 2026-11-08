# Opulse atoms-v2: the six kinds of atoms (specification)

Spec version: `atoms-v2/0.5` (2026-11-04). Status: binding interface for the core, UI, experiment
and tasks work. It implements the confirmed foundation (user, 2026-11-04). Changes to this file bump
the spec version and are listed in section 17.

Words used with a fixed meaning: **must** (required), **must not** (forbidden), **may** (allowed).

## 1. Summary

A world declares its layer 0 with four kinds of atoms:

| kind | Python record | question it answers | example (integer world) |
|---|---|---|---|
| `object` | `ObjectSpec` | what exists? | `int` |
| `operation` | `OperationSpec` | what can be done in one step? | `+`, `succ`, is-zero |
| `combinator` | `CombinatorSpec` | how are steps put together? | sequence, branch, recursion |
| `observation` | `ObservationSpec` | what can the learner see? | inputs and result |

Two more kinds are definable (section 19): `law` (`LawSpec`, sigil `#`: a statement that always
holds, usable as one rewrite step) and `bridge` (`BridgeSpec`, sigil `~`: a translation whose
diagram commutes). Worlds may give laws at layer 0 as axioms. **Templates** (`TemplateSpec`)
produce definitions of any kind from kind and value parameters.

A learner or a generator writes **definitions** of any of the six kinds. Every definition is one
`Definition` record and goes through one pipeline (section 9):
`written -> checked -> callable -> verified -> promoted`. A promoted definition is used as one step
under a chosen **boundary** (section 10). The four invariants (section 11) are hard rules.

The current Opulse (operations only, fixed combinators substitution / branch / recursion, fixed
value types) is the special case "dialect `legacy-v1`" (section 13). Published worlds and data
read unchanged through that dialect, except the clock world (section 14).

## 2. Values

### 2.1 Value

```text
Value = Int | Text | Card
Int   = an integer of unbounded size (bool is NOT an Int)
Text  = a finite sequence of Unicode code points
Card  = Card(sort: SortRef, tag: str, fields: tuple[Value, ...])
```

- `sort` names the object (section 4) the card belongs to, with its static parameters, for
  example `bool`, `list[int]`, `perm[4]`, `fraction`.
- `tag` is one of the tags the sort declares. A record sort has one tag (by convention the sort
  name). `bool` is the sort with tags `false` and `true` and no fields.
- `fields` is an ordered tuple. A tag declares either a fixed list of named fields or one
  variable-length field list `items: T` (used by sequences such as `list[T]`).
- Values are finite trees. There are no cycles and no infinite values (section 16).

Two values are **equal** (kernel equality) when they have the same constructor, the same sort
and tag, and equal fields in order. Kernel equality is structural on the canonical
representation (section 4.3). A world operation `eq` is a separate thing and may differ (for
example an IEEE `eq(NaN, NaN) = false` in a bit-level float world).

### 2.2 JSON encoding (schema `opulse.value/2`)

```json
{"t": "int", "v": 5}
{"t": "str", "v": "abc"}
{"t": "<sort>", "tag": "<tag>", "f": [<value>, ...]}
```

The legacy encodings `{"t": "int"|"bool"|"str"|"list[int]"|"perm"|"note"|"melody"|"grid"|"state"|..., "v": ...}`
remain valid input and output in dialect `legacy-v1`. They are decoded with a **world-context
codec** (section 13.3): the codec, not the tag alone, decides the sort.

### 2.3 Host representations

A world may store a given sort in a host representation (Python `int`, `tuple`,
`Permutation`, the robot state object) for speed. The world then must declare a codec
`to_card / from_card` that is total and bijective on valid values. The host representation
must not change any result, failure, step count or trace.

### 2.4 Integers derived from zero and successor

The world `successor` (and new teaching worlds) may declare `nat = compose <zero | succ(nat)>`
as an object. `3` then has the derivation `succ(succ(succ(zero)))`. This derivation is
unfoldable and costs three `succ` steps. The kernel still carries integers as `Int`; the
derivation is a teaching object, not the carrier.

## 3. Outcome

Every evaluation returns an `Outcome`:

```text
Outcome = Ok(value: Value) | Bottom(reason: str) | Unknown(resource: str)
```

- `Bottom(reason)` is a domain failure: division by zero, a blocked robot move, no matching
  case arm, a value outside `valid`. Reasons are short identifiers (`div_zero`, `blocked`,
  `no_branch`, `invalid`, `measure`, `overflow`, `nan_condition`).
- `Unknown(resource)` means the evaluation ran out of a resource: `fuel` (layer-0 step budget),
  `depth`, `nodes`. Unknown is not a value.
- Calls and constructors are **strict**: a `Bottom` argument makes the call `Bottom` with the
  same reason; an `Unknown` argument makes it `Unknown`. Arguments evaluate left to right and
  evaluation stops at the first argument that is not `Ok` (later arguments are not evaluated
  and charge nothing). `Let` is strict in the same way. Dialect `legacy-v1` differs (section
  13.2, rule 8).
- Comparison of outcomes (`outcome_equal`): `Ok(a) == Ok(b)` iff `a` equals `b`;
  `Bottom(r1) == Bottom(r2)` is true regardless of reason (legacy rule: two NaN are equal);
  `Unknown` is never equal to anything, including another `Unknown`. A grader must never
  judge an `Unknown` result correct.
- Containers must not hold `Bottom`. To keep a failure as data, a definition must use the
  explicit lift: `lift[T] = bot(reason: str) | val(T)`, built by the non-strict operation
  `catch`. `defined(x)` (legacy) is the non-strict test `Bottom -> false`.
- Legacy codec: the legacy NaN value and `{"t": "nan", ...}` decode to `Bottom`; `Bottom`
  encodes back to the legacy NaN in dialect `legacy-v1`.

## 4. Objects: `ObjectSpec`

### 4.1 Forms

An object is declared by one of two methods plus one switch:

1. **compose**: a sort is a set of tags; each tag has fields. Special cases:
   - record: one tag with named fields, `pair = compose <pair(a: int, b: int)>`;
   - variant: several tags, `option[T] = compose <none | some(value: T)>`;
   - sequence: one tag with variable `items`, `list[T]` may be either the native sequence
     `compose <items(T*)>` or the structural `compose <nil | cons(head: T, tail: list[T])>`;
   - recursive and mutually recursive sorts: declared together as one `group`. Each group must
     be strictly positive (a sort appears in its own fields only as a field type, never as a
     function argument) and must have at least one base tag (a tag whose fields do not
     mention the group) so that finite values exist.
2. **refine**: `refine base where valid; canon`.
   - `base`: an existing sort.
   - `valid: base -> bool`: which representations are values.
   - `canon: base -> base` (optional): the canonical representative.
   - `valid` and `canon` are nodes over the single variable `x` (the base representation);
     record fields are read with the base sort's accessors, for example `record.den(x)`.
   - Obligations (each recorded as evidence, section 8):
     `canon` is total on valid values; idempotent (`canon(canon x) = canon x`); keeps validity
     (`valid x -> valid(canon x)`); and every interface operation **respects** canon
     (`canon x = canon y -> op(x) = op(y)`, per argument position).
   - `valid` and `canon` must be written in the terminating sublanguage: no `Blocks/Jump`;
     `Rec` only with a measure (section 6.3). A definition whose `valid` or `canon` can return
     `Unknown` on its verified scope must not be stored.
3. **seal** (switch, `sealed: true`): only the operations listed in `interface` may build or read
   the inside. Other definitions see only the sort name and the interface. Unfolding for audit
   may still show the inside.

A **named constant** is an `ObjectSpec` with form `constant`. It introduces no new sort. Its body
is a closed term of an existing sort, for example `three = succ(succ(succ(zero)))`. Unfolding
replaces the name with the term; evaluation charges the steps of the term.

### 4.2 Static parameters

A sort may take static parameters: type parameters (`list[T]`) and integer parameters
(`perm[n]`, `uint[k]`). They are fixed at instantiation. Sizes known only at run time go into
`valid` (the robot map width is checked by `valid`, not by a type parameter). A world constant
(for example the name list of the `rel` world) read by `valid` is part of the world hash; a new
constant value means a new world version.

### 4.3 Entry: `make` and the `enter` rule of each edge

Every input edge `inputs[i]` and the output edge of an operation declares an entry rule:

| rule | meaning |
|---|---|
| `bottom` | a value outside `valid` gives `Bottom(invalid)` |
| `normalize` | apply `canon` of the sort (for example `n mod 12`) |
| `saturate(lo, hi)` | clamp into the range |
| `fold(name)` | a named legacy folding rule (section 13.2) |

The default for a refine sort is `normalize` when it has `canon`, else `bottom`. The check and
the canonicalisation happen at the semantic position of `make` (the edge) and are charged
there in exact layer-0 steps (`canon_cost: counted`), or declared free for a given layer-0 sort
(`canon_cost: free`, part of the world version). Moving from a refine sort to its base is
implicit. Narrowing from the base to the refine sort is explicit (`make`), except the
legacy-v1 int->note rule (section 13.2).

### 4.4 Record

```yaml
kind: object
name: fraction
form: refine
base: {record: {num: int, den: int}}
valid: "den(x) != 0"              # a Node over the variable x (section 6)
canon: "reduce x by gcd; den > 0" # a Node over x
sealed: true
interface: [make_fraction, num, den, fraction_eq]
params: []
equality: canonical               # canonical | none
canon_cost: counted
```

## 5. Operations: `OperationSpec`

```yaml
kind: operation
name: add
role: combine                     # transform | combine | decide | relate | act
inputs: [{sort: byte, enter: bottom}, {sort: byte, enter: bottom}]
output: {sort: byte, enter: normalize}
rule: "(a + b) mod 256"           # human-readable rule, required
errors: []                        # Bottom reasons this operation can return
impl: {host: "<module>:add", digest: "<sha256 of the source>"}  # or {table: ...} or {body: <Node>}
cost: 1                           # exact layer-0 steps of one call
strict: true
reads_params: []
```

- `role` is a label only. `relate` operations return `set[lift[T]]` (several results);
  `act` operations take and return a state sort (they change state).
- `impl.host` is allowed only at layer 0 (given atoms). The digest of the host source goes into
  the world lock; a change of the source changes the world version. Definitions written by a
  learner or a generator must not use host code.
- Every given operation must state its rule, its errors and its cost.
- A host implementation must be a deterministic function of its arguments without side effects
  (state changes are new state values returned, never mutation). Memoized recursion, fast paths
  and replay rely on it; an atom that mutates its arguments is outside the model. The cost of a
  call may be a declared function of the arguments (`cost_rule`), charged before the call.
- Comparison operations of legacy worlds (`<`, `==` on int, str, list order) are given
  operations with role `decide`. A sealed sort has no order unless its interface declares one.

## 6. Combinators: `CombinatorSpec` and the kernel nodes

### 6.1 Kernel nodes

All bodies (of operations, combinators, observations, `valid`, `canon`) are trees of these
nodes. Interpretation, tracing, type checking and cost accounting use the same tree.

| node | fields | meaning |
|---|---|---|
| `Var` | `name` | a parameter or a `Let` name |
| `Lit` | `value` | a literal value (checked against the expected sort) |
| `Call` | `fn, args` | call an operation, a definition, or an operation parameter; strict; names resolve to a local `Rec` function, then a scope definition or atom, then a variable holding an operation reference (an operation parameter must not share a name with a scope name) |
| `Let` | `name, value, body` | evaluate `value` once, bind it |
| `Case` | `arms: [(cond, body)], default` | ordered, short-circuit; first true arm wins |
| `Rec` | `fn, params, body, measure` | a local recursive function (section 6.3) |
| `Blocks` | `vars, entry, blocks` | a flat program with labelled blocks (section 6.4) |
| `Jump` | `target` / `cond, then, else` | block terminator: goto, conditional goto |
| `Halt` | `value` | block terminator: return |

Conditions: `Test(node)` (the node evaluates to a `bool` card), `And`, `Or`, `Not`, `True`.
Conditions evaluate left to right with short-circuit. If an evaluated condition is `Bottom`,
the whole `Case` is `Bottom(nan_condition)`. If no arm matches and there is no default, the
result is `Bottom(no_branch)`.

A world opens a subset of nodes in `combinators.nodes`. A body that uses a node the world does
not open fails the type check.

### 6.2 Standard library combinators

A standard combinator is a `CombinatorSpec` with operation parameters and a public unfold rule
written with kernel nodes:

| name | parameters | unfold rule |
|---|---|---|
| `seq` | `f, g` | `x |-> g(f(x))` |
| `twice` | `f` | `x |-> f(f(x))` |
| `repeat` | `f, n` (static) | `n` nested calls of `f` |
| `fold` | `f, z` | `Rec` over a list: `fold(f, z, nil) = z`, `fold(f, z, cons(h, t)) = f(h, fold(f, z, t))` |
| `map` | `f` | `Rec` over a list |
| `repeat_until` | `body, stop, max, on_exhaust` | section 13.2 for the legacy robot form |
| `search` | `bound, p` | least `i` in `0..bound` with `p(i)`; `Rec` with measure `bound - i` |

A world may declare more. A new combinator definition (kind `combinator`) has the same shape:
parameters (values and operation parameters), a body, and its unfold rule is "substitute the
passed operations and arguments into the body".

### 6.3 `Rec`

`Rec(fn, params, body, measure)` binds a recursive function `fn`. The body may call `fn`.

- `measure` is a Node over `params` that returns a non-negative Int. At each recursive call the
  kernel evaluates the measure of the new arguments; it must be smaller than the measure of
  the current arguments, else the call is `Bottom(measure)`. The measure is a termination check,
  not part of the computation: it is not charged and not traced, but it runs under the same fuel
  and depth limits as a separate budget; a measure that does not finish makes the call `Unknown`.
- The recursion counter is updated by the world's own operations and charged like any call
  (clock `%`, bits `shift_right`, negative counters in legacy worlds). The kernel never inserts a hidden
  `n - 1`.
- `measure: fuel` (allowed when the world sets `combinators.recursion: fuel`) means: no measure
  check; the recursion is bounded only by fuel and depth, and running out is `Unknown`. This is
  how a learner writes recursion without proving termination (the experiment worlds use it).
- `measure: legacy` (dialect `legacy-v1` only) means the same, with the legacy depth limit
  (10 000); exceeding it is `Unknown(depth)`.
- `combinators.recursion` of a world is one of `legacy`, `measure` (every `Rec` needs a measure
  node), `fuel` (a `Rec` may use `measure: fuel`), `none` (the world does not open `Rec`; a
  machine world repeats with `Blocks/Jump`). `combinators.nodes` may also list the block
  terminators `Jump`, `CondJump`, `Halt` next to `Blocks`.

### 6.4 `Blocks` and `Jump`

`Blocks(vars, entry, blocks)` is a program with a program counter. Each block is a list of
assignments `var := node` and one terminator (`Jump`, conditional `Jump`, `Halt`). Every
executed jump charges one control step. Loops stop when the fuel runs out (`Unknown(fuel)`).
A `Blocks` program is a combinator card. It is not a value and cannot modify itself
(section 15).

### 6.5 Fuel and steps

- **Layer-0 steps**: each call of a given operation charges its declared `cost` (default 1);
  each executed `Jump` charges 1. Calls of definitions charge nothing themselves; their bodies
  charge.
- **Fuel** is a budget in layer-0 steps. When it runs out the result is `Unknown(fuel)`.
- The step count and the fuel are always computed on the full unfolding to layer 0, whatever
  boundary is shown and whatever is promoted. A fast path for a promoted definition (section
  9.7) must charge the exact layer-0 step count of the unfolding.
- Legacy step count = the old `base_ops` count (calls of base operations).

## 7. Observations: `ObservationSpec`

### 7.1 World side

```yaml
observation:
  truth: robot_state                # the sealed full state
  probes:                           # given read operations on the truth
    - {name: front_wall, sort: bool, reveals: ["whether the cell in front is a wall"]}
  capabilities:                     # per agent; default agent "learner"
    learner: {channels: [results, errors, renders, traces, steps, memory], probes: all}
  show: {input: full_state, result: full_state}   # what a task shows; may only narrow
  judge_view: full_state            # default; per task it may be a declared projection
```

- The truth is sealed. Only probes read it.
- `channels` lists what the learner sees: results, error reasons, renders, traces, step counts,
  memory (provisional default: all six).
- Grading always uses `judge_view` applied to the full truth state, never the learner's view
  (invariant 3). Values: `full_state` (default), `contract_projection(fields)`.

### 7.2 New observations (kind `observation`)

```yaml
kind: observation
name: front_free
reads: [front_wall, front_water]     # granted probes only
memory: null                          # or {sort: int, init: <Lit>, step: <Node over memory and reads>}
body: "not front_wall and not front_water"   # a Node over the probe values and the memory
```

Rules checked by the type checker:

- The body and `memory.step` may call only: probes in `reads` (each granted to the agent),
  other observation definitions, and operations whose inputs do not include the truth sort.
- Memory is a fold over past observations: `memory.step(previous_memory, current probe values)`.
  Memory never reads the truth directly.
- An observation cannot change the truth: it has no `act` operation in its dependency closure.

Unfolding an observation shows the probes it reads ("front free" unfolds to two observations).

## 8. Definition record

```yaml
id: "<world>@<version>/<name>"
name: MUL
kind: operation                       # object | operation | combinator | observation
origin: invented                      # given | invented
layer: 1                              # 0 for given; else at least 1 + max(layer of depends_on)
depends_on: [add, dec, jump]
spec: {...}                           # the ObjectSpec / OperationSpec / CombinatorSpec / ObservationSpec fields
body: <Node>                          # or {host: ...} for given atoms (HostRule)
evidence:
  method: exhaustive                  # exhaustive | bounded | sampled
  scope: {domain: "byte x byte", size: 65536, description: "all 8-bit pairs, full machine state"}
  seed: null                          # required for sampled
  checks: [unfold_equivalence, boundary_invariance]   # obligations covered
  world_hash: "<sha256>"
  deps_hash: "<sha256 of the transitive dependency records>"
contract:
  guarantees: "R0 = a * b mod 256"
  may_change: [R2, flags]             # descriptive; v1 promotion still needs full-state equality
  keeps: [memory]
cost:
  length: 14                          # nodes in the body
  steps: {min: 3, max: 1020, mean: 511.5, over: "verification scope"}   # exact layer-0 steps
  reuse: 0                            # call sites in other stored definitions and solutions
status: promoted                      # written | checked | callable | verified | promoted
```

- `layer` of an invented definition is at least 1 + the highest layer of its dependencies (a
  definition may be placed higher, for example on a design row; never lower). Generated operations
  of an object have the object's layer; those of world objects are layer 0.
- `origin: given` marks world atoms. `origin: invented` marks definitions written by a learner
  or a generator. Origin is never a performance shortcut.
- Evidence is invalid when the world hash or a dependency changes. The library then resets the
  status to `callable`.
- Evidence methods and their rights:

| method | meaning | may be stored and called | may be promoted |
|---|---|---|---|
| `exhaustive` | every input in the scope **and** every claimed answer checked | yes | yes, scope carried |
| `bounded` | every input up to a size bound | yes | yes, scope carried |
| `sampled` | seeded random inputs; `seed` and count recorded | yes | **no** |

  The library must never turn an exhaustive claim into a sampled one silently, and must never
  widen a scope.

## 9. The pipeline

1. **written**: the record has `name`, `kind`, `body`, `depends_on`.
   `depends_on` must equal the set of names the body references.
2. **checked**: the type checker accepts the body: every name resolves in the world plus the
   library; sorts match; only opened nodes are used; observation and seal rules hold;
   `valid`/`canon` use the terminating sublanguage; no dependency cycle except inside a
   declared `Rec` or sort group.
3. **callable**: the kernel runs the body and unfolds it to layer 0 on at least one input.
   Calls are charged by the unfolded layer-0 steps.
4. **verified**: evidence is recorded (section 8) with the obligations of the kind:

| kind | obligations |
|---|---|
| operation | the result agrees with the reference (an oracle, a given operation it claims to equal, or a declared table) on the scope; `unfold_equivalence` |
| object | refine: canon total, idempotent, keeps validity; every interface operation respects canon; seal: no outside definition reads the inside. Invented vs given: an abstraction map `abs` that commutes with the interface, checked exhaustively in a recorded scope; else seeded random interface-program tests, labelled `sampled` |
| combinator | for every passed operation in a recorded finite family (the world's given operations and short compositions of them, listed in the scope) and every input in the scope, the combinator equals its unfold rule; always `bounded` or `sampled` |
| observation | dependency check (only granted probes and memory); the value agrees with the claimed reference on the scope (required for promotion); the truth is unchanged; two truth states with equal probe values give equal observations |

5. **accounted**: `cost.length`, `cost.steps`, `cost.reuse` are filled.
6. **stored**: the library keeps the record and its dependency records. The definition can be
   called by name. It is not yet one step for display.
   A verification domain is never empty, and every input of it is checked (observations: every
   state of the domain; extra histories only order states for memory). Evidence also records the
   content hash of the definition and a digest of the layer-0 atom implementations; a change of
   either drops the evidence (also when a library is reloaded).
7. **promoted**: allowed only when the method is `exhaustive` or `bounded` and the
   unfold-equivalence check passed on the scope **on the full execution state** (value,
   `Bottom` vs `Ok`, side effects on the state, layer-0 steps). The record keeps its scope and
   contract. Under a boundary that does not open it, a promoted definition is shown as one step.

### 9.7 Fast paths

A promoted operation may carry a fast implementation used only inside its verified exhaustive
scope. The fast path must return the same outcome and charge the exact layer-0 step count
recorded for that input (or computed by an exact formula checked on the whole scope). Outside
the scope the kernel runs the unfolding.

## 10. Boundaries

A boundary decides which calls of definitions are shown as one step and which are opened. It
never changes the evaluation (invariant 2).

```python
@dataclass(frozen=True)
class Boundary:
    depth: int | None = None            # open definitions of layer >= depth (None: open none by depth)
    open_names: frozenset[str] = ...    # position: open these definitions wherever they occur
    keep_names: frozenset[str] = ...    # position: keep these as one step even if depth would open them
    open_paths: frozenset[tuple[int, ...]] = ...   # position: open the call at these call paths only
    kinds: frozenset[str] = ALL_KINDS   # kind: open only along these kinds (object|operation|combinator|observation)
```

A call of definition `d` at call path `p` is **opened** iff `d` is not given, `d.kind` is in
`kinds`, `d.name` is not in `keep_names`, and one of: `d.layer >= depth`, `d.name in open_names`,
`p in open_paths`. Given atoms are never opened.

- The legacy `cut(known, known_layers)` is `Boundary(depth=known_layers, keep_names=known)`
  restricted to kind `operation`.
- "Unfold everything" is `Boundary(depth=0)`. "Unfold nothing" is `Boundary()`.
- Examples from the design: DOT kept; DOT opened with MUL kept (`open_names={DOT}`, `keep_names={MUL}`);
  everything to layer 0 (`depth=0`).
- Kind examples: MUL opens into additions, `three` opens into `succ` calls, `while` opens into
  jumps, `front_free` opens into two probes.

**Unfold-equivalence verifier** (`verify.unfold_equivalent` in the package): for an expression,
a list of boundaries and inputs, it evaluates under each boundary and checks equal outcome,
equal final state, equal layer-0 step count, and that the flattened view of each boundary
expands to the layer-0 trace.

## 11. The four invariants and their tests

| invariant | rule | test that must exist |
|---|---|---|
| I1 always unfoldable | every promoted definition unfolds to layer 0 and gives the same outcome | for every stored definition: evaluation with `Boundary()` equals evaluation of the full unfolding, on the evidence scope |
| I2 boundary never changes a result | a boundary changes only step visibility | random expressions x random boundaries: outcome, state and layer-0 steps identical; flattened views splice exactly |
| I3 observation never changes facts | grading uses `judge_view(full truth)` | an observation definition run on a state leaves the state unchanged; grading with two learner views gives the same verdict |
| I4 promotion carries scope and contract | evidence and contract travel with the promoted record | promoting without evidence, with `sampled`, or with a changed world hash fails; a derived world lists the scope of each promoted definition |

## 12. World declaration (schema `opulse.world/2`)

```yaml
world: clock
version: 2
dialect: atoms-v2                     # or legacy-v1
params: {}
constants: {}
objects: [hour]                       # ObjectSpec records (given, layer 0)
operations: [add, sub, mul, div, mod, neg, reverse, triangle, popcount, digitsum]
combinators: {nodes: [Var, Lit, Call, Let, Case, Rec], library: [], recursion: legacy}
observation: {truth: null, show: {input: values, result: value}, judge_view: full_state}
lock: {host_digests: {...}, constants_hash: "...", world_hash: "..."}
```

**Extra members.** A world, an object, an operation and a probe may carry extra members
(world `title`, `title_zh`, `source`, `codec`; operation `symbol`, `input_names`; object
`host`, `doc`; probe `impl`; others allowed). Readers keep them in an `extra` dict and write them
back unchanged. The world hash excludes the display-only members `title`, `title_zh`, `doc`,
`source`, `symbol`, `input_names`, and includes every other member.

**Derived world**: `{"extends": "<world>@<version>", "promoted": ["<definition id>", ...]}`.
A derived world adds promoted definitions as layer-k atoms with their scope and contract.
World B + promoted MUL gives the same results as world A with given MUL; step counts and
learning may differ (B charges the unfolded steps).

## 13. Legacy compatibility: dialect `legacy-v1`

### 13.1 Mapping of the current code

| current | atoms-v2 |
|---|---|
| `core/types.py` `ValueType` (int, bool, str, list[int], perm[n], grid, note, melody, state, colour, direction) | given `ObjectSpec`s of the world, with host codecs |
| `Operator` with `definition is None` (base atoms, `CUSTOM` primitives) | `Definition(kind=operation, origin=given, layer=0, body=HostRule)` |
| generated `Operator` with a definition | `Definition(kind=operation, origin=invented, layer=recursive_layer)` |
| `definition_type` SIMPLE / BRANCH / RECURSIVE | body without `Case` / with `Case` / with a self call in `Case` (`Rec`, `measure: legacy`). The old `definition_type` is kept as metadata, never re-derived |
| `Search` node | `search` combinator: bounded `Rec` + ordered `Case`; legacy steps count only the atoms inside the predicate; `definition_type` stays SIMPLE |
| `Compare` in conditions | a call of a given `decide` operation (`int.lt`, ...) with legacy order |
| `NAN` | `Bottom`; `same_value(NAN, NAN)` stays true |
| `OperatorRegistry` | the definition library of a world |
| `trace/tree.cut(known, known_layers)` | `Boundary(depth=known_layers, keep_names=known)` |
| interpreter `Result(value, base_ops, calls)` | `Outcome`, layer-0 steps = `base_ops` |
| robot `Skill` (repeat / guard) | `repeat_until` and `Case` over probes, dialect form |
| `Semantics.mode` exact / legacy / modular | output edge `enter`: `bottom` on overflow / `fold(legacy_bound)` / `normalize(mod m)` |

### 13.2 Dialect rules (all required for golden equality)

1. Robot `repeat_until(body, stop, max)`: `max = 0` returns the state; each round checks `stop`
   first, then runs `body`; after `max` rounds it returns the last state **without** checking
   `stop` again. An illegal `forward` is `Bottom(blocked)`, never "stay in place".
2. Pitch: where a `note` parameter receives an `int`, the dialect inserts a counted
   `make_note` check `0..127`; out of range is `Bottom(invalid)`. `note -> int` is implicit.
3. Legacy integer mode: results fold symmetrically by the bound; `reverse`, `triangle`,
   `digitsum` preprocess the input with `abs(a) % bound`; division and modulo by zero use
   divisor 1. These are input-edge and output-edge rules of the dialect (`fold(legacy)`).
4. Legacy recursion: counters are updated by the world operations (clock `%`, bits `shift_right`,
   negative counters). No measure check; depth limit 10 000.
5. `search` keeps its old node, old steps and old traces.
6. Old tags: `perm` gets its `n` from the world; packed integer aliases (`swap`, `recolour`)
   are expanded by the codec; `nan` maps to `Bottom`; the empty grid crop `((0,),)` stays.
7. Conditions: short-circuit `and`/`or`; a NaN condition aborts the definition (legacy reason
   `nan_condition`).
8. NaN flows as a value: every argument of a call is evaluated even when an earlier one is
   `Bottom`; a given atom with `Bottom` arguments is still called and charged (legacy host
   functions return NaN, `defined` returns 0); a definition with `Bottom` arguments is entered
   with its parameters bound to `Bottom`; `Let` binds `Bottom`. Only `Unknown` stops evaluation.
   Comparisons are given `decide` atoms of cost 0 (legacy step counts include only base
   operations).

### 13.3 Codec and golden tests

The codec of a world maps `legacy tag -> sort` with the world context (for example `perm -> perm[n]`,
clock `int -> hour`). Golden tests read every published example in
`docs/assets/data/worlds/<w>.json` (and seed files, steps files, tasks) and must reproduce the
outputs, failures, step counts and traces through the new kernel in dialect `legacy-v1`. The
only exception is the clock world (section 14), whose data is regenerated.

## 14. Clock world: a true clock (world `clock`, version 2)

- Object `hour = refine int; canon n |-> n mod 12` (values 0..11). Entry rule `normalize` on every
  operation input, every literal and every task input: `14` enters as `2`, `-4` enters as `8`.
- Every operation takes canonical hours and returns an hour (`out.enter: normalize`).
  `reverse`, `digitsum`, `triangle`, `popcount` act on the 0..11 representation, so they are
  well defined on hours. Division and modulo by `0` are `Bottom(div_zero)`.
- Recursion counters use the clock operations (as before).
- The clock data in `docs/assets/data/worlds/clock*` and the site examples are regenerated. Old
  golden examples whose inputs are outside 0..11 are not compared. This is the only intended
  change to published answers.

## 15. Computer world v1 (Harvard style)

- Objects: `byte = refine int where 0 <= x < 256`; `reg = compose <r0 | r1 | r2 | r3>`;
  `flag = bool`; `machine_state = compose <machine(regs: array[4, byte], mem: array[256, byte], zero: flag, carry: flag)>`
  (registers are fields of the machine state).
- Operations: `read(state, reg) -> byte`, `write(state, reg, byte) -> state`, `load`, `store`,
  `add` (wraps, sets carry), `dec`, `is_zero`. Each with rule, errors, cost 1.
- Combinators: `Blocks/Jump` with conditional jump; sequence. The program is a separate
  combinator card, not in memory, and cannot modify itself.
- Observation: inputs and output, or all registers; per task.
- First experiment target: `MUL` as an invented operation (loop of `add` and `dec`), verified
  exhaustively on 65 536 input pairs with the full machine state; contract states which
  registers it changes.

## 16. Not in v1 (documented limits)

- (Moved into scope 11-04: definitions as objects, meta worlds, world building and self-modifying
  code are built by the meta level; see the atoms-meta spec on the meta branch.)
- Infinite objects: streams, codata, corecursion.
- Narrow (contract-only) promotion: v1 promotion requires full-state equality.
- Proof certificates as evidence method; tolerance / prefix / three-valued answers.

## 18. Additions in 0.3

### 18.1 Open kinds
A world declares `open_kinds`, a subset of the six kinds (default: the four layer-0 kinds, so older declarations keep their hash; JSON: a sorted
list; part of the world hash). The library refuses to store an invented definition whose kind
is closed. Old Opulse is `open_kinds = [operation]` (`legacy_world_decl`).

### 18.2 More combination modes
Each has a public unfold to kernel nodes and exact layer-0 cost; each passes through the library
pipeline with bounded or sampled evidence over a declared operation family.

| mode | form | unfold |
|---|---|---|
| fixpoint until stable | `@fix[step] (x, height)` | `Rec` with measure = remaining height; equal consecutive values stop; exhausting the declared finite height is `Bottom(not_stable)` |
| memoized recursion | `Rec(..., memo=True)` | same outcome and the same charged steps as the plain recursion; the kernel reports the memo work separately (`Run.work`) |
| turns | `@turns[observe_i, choose_i, apply] (state, schedule)` | each agent chooses from its own observation only; schedules: round-robin with a count, an explicit order, or all orders up to a bound (the list of distinct final states) |
| derived structural recursion | `@S.fold[on_tag...] (value)`, `S.size(value)` | every compose object (and sort group) gets its fold (one case per tag, recursive fields folded first; measure `S.size`) and its size (constructor count, cost 1) |

A combinator body may pass its own operation parameter on to another combinator; this records a
dependency edge. Literals may hold an operation reference (`{"t": "fn", "v": name}`) and a
declared failure (`{"t": "bottom", "v": reason}`).

### 18.3 Generic probes
Probes are the atoms of kind `observation` named in `observation.probes`; they take the truth
value. An observation may call probes and other observations; it may not call an operation whose
role is `act` or whose inputs include the truth sort.
The observed value is the observation's subject (`ObservationSpec.extra["subject"]`, default
`s`). `?p{s}` is `Call(p, (Var(s),))`; the subject may be passed only to probes and observations.

Since 0.5 (decision R13-D): a derived observation may apply pure definitions (operations,
combinators, bridges, other observations) to observed values, provided nothing in its dependency
closure has role `act` or takes the truth sort, and the truth subject still reaches only probes
and observations. An observation may also observe public values: `extra["inputs"]` lists several
typed inputs, none of the truth sort; it is then a pure function of those inputs, `facts_unchanged`
applies to the inputs and `non_interference` does not apply (recorded as `n/a`).

### 18.4 Content identity
`Definition.content_hash(deps)` hashes the kind, the spec without display-only members, the body
and the content hashes of the dependencies. Parameter names are semantic (they bind the body).
Evidence records the content hash; promotion refuses a definition whose content hash changed. A
promoted definition is immutable: a change is a new definition (`force_new_version`) that
inherits no evidence.

### 18.5 ASCII notation
The only written form of definitions, prompts and data is ASCII (`atoms.notation`: printer and
parser, exact inverses). Four kinds, four brackets: objects `Frac<1, 2>`, `List<1, 2>`;
operations `mul(3, 4)`; combinators `@twice[double] (3)`; observations `?even{12}`.
Comparisons are operations (`lt`, `le`, `eq`, `ne`); only given `+ - *` may be infix.
Declarations start with `obj`, `op`, `comb`, `obs` and end with `given` or `L<n>`. The sigils
`@` and `?` are notation only: stored names are plain identifiers. Generated names: objects
`A0`..`Z0`, `A1`..; operations `f6`; combinators `@k3`; observations `?q4`; old Unicode
operator symbols map to `f<n>` through the legacy codec.

### 18.6 Metered atoms
`Atom(metered=True)` receives a context whose `call(defn, args, extra_defns, budget)` evaluates
inside the running evaluation: the same step counter, fuel, depth and trace (inner calls are
children of the atom's frame). The atom itself costs 0; a budget overrun is `Unknown(fuel)` for
the atom. This is how `eval(code, args)` keeps exact layer-0 steps (meta level).

## 19. Laws, bridges and templates (0.4)

### 19.1 Laws (kind `law`, sigil `#`)
`LawSpec(name, vars, statement)`: `statement` is a boolean node over the typed `vars`. ASCII:
`law #mul_comm: eq(mul(a, b), mul(b, a)) for a: Int, b: Int L1` (`given` for axioms). Evidence
is the usual: every tuple of the domain makes the statement `Ok(true)`; the scope is recorded and
never widened (a law checked on 8-bit values is not a law for all widths).
An equation `eq(lhs, rhs)` may serve as ONE rewrite step `by #law` in a derivation once promoted.
The step matches one side against a subterm (law variables bind subterms) and substitutes the
other side. The derivation must still unfold to layer 0 with the same result: the rewrite is
replayed as computation, and every binding of the law's variables must lie inside the verified
scope; outside the scope the step is refused. A rewrite step costs no layer-0 step; the charged
steps are those of evaluating the final expression.

### 19.2 Bridges (kind `bridge`, sigil `~`)
`BridgeSpec(name, source, target, map, domain, interface)`: `map` is a node over `x`, `domain` an
optional boolean node over `x` (partial bridges: outside it the bridge is
`Bottom(outside_domain)`), `interface` pairs `(source operation, target operation)`. ASCII:
`bridge ~to_frac: MyFrac -> Frac`, applied as `~to_frac(x)`. Obligation (`commutes`): on the
recorded scope, translate-then-compute equals compute-then-translate for every interface pair.
Cross-world bridges name `world@version:sort`. The invented-vs-given abstraction check
(section 8) and the meta compiler are bridges. A composed bridge has its own evidence.

### 19.3 Templates
`TemplateSpec(name, params, produces, pattern)`: parameters are (name, kind or sort); the
pattern is the produced spec with `$param` placeholders. Example: `obj Quot[T, canon] = refine T
canon(canon)`; `Frac = Quot[Pair<Int, Int>, reduce]`, `Hour = Quot[Int, mod12]`. A template is
checked once as a family (bounded or sampled evidence over a recorded finite family of
instantiations, never exhaustive). Every instantiation is an ordinary definition with its own
pipeline and evidence; it may cite the template's evidence only for arguments inside the recorded
family. Content identity covers template and arguments; instantiations list the template in
`depends_on`, so a boundary can open `Frac` into `Quot[...]` and then into its body.

## 17. Reference implementation (Python) and versions

Package `opulse.atoms` (new; the old code keeps working unchanged):

| module | contents |
|---|---|
| `atoms.values` | `Card`, `Ok`, `Bottom`, `Unknown`, `outcome_equal`, `value_equal`, JSON codec `opulse.value/2` |
| `atoms.nodes` | kernel nodes (section 6.1), conditions, JSON round trip, `length()` |
| `atoms.kernel` | `evaluate(node, env, world, library, fuel) -> (Outcome, Steps, Trace)`; strictness, Case, Rec, Blocks |
| `atoms.spec` | `ObjectSpec`, `OperationSpec`, `CombinatorSpec`, `ObservationSpec`, `Definition`, `Evidence`, `Contract`, `Cost`, `Status` |
| `atoms.world` | `WorldDecl`, derived worlds, world hash |
| `atoms.boundary` | `Boundary`, `opens()`, legacy `from_cut()` |
| `atoms.verify` | `unfold_equivalent`, evidence builders (exhaustive / bounded / sampled), object, combinator and observation obligations |
| `atoms.library` | `Library`: add, check, run, verify, account, store, promote; invalidation |
| `atoms.legacy` | dialect `legacy-v1`: registry and robot skills -> kernel scope; legacy definition records |
| `atoms.golden` | golden harness: every published example through the current engine or the kernel engine |
| `atoms.check` | the type checker of pipeline step 2 |
| `atoms.objects` | object operations (constructors, accessors, `make`, seal) and object obligations |
| `atoms.observations` | robot probes, observation runs over histories, non-interference, `judge` |
| `atoms.combinators` | the standard combinators, `instantiate`, combinator obligations over an operation family |
| `atoms.notation` | the ASCII notation: printer, parser, generated names (section 18.5) |
| `atoms.random_programs` | seeded random kernel programs and hypothesis strategies for the invariant tests |

JSON schemas: values `opulse.value/2`; definitions `opulse.definition/2`; worlds `opulse.world/2`.
Each JSON object written by the reference implementation carries its `schema` field.

### Changes

- `atoms-v2/0.1` (2026-11-04): first version.
- `atoms-v2/0.5` (2026-11-05): observations may call pure definitions and observe public values (18.3, R13-D).
- `atoms-v2/0.4` (2026-11-05): six kinds (law, bridge), templates (section 19); ASCII only.
- `atoms-v2/0.3` (2026-11-04): section 18 (open kinds, more combination modes,
  generic probes and the observation subject, content identity, ASCII notation, metered atoms).
- `atoms-v2/0.2` (2026-11-04): `measure: fuel` and `combinators.recursion`; strict argument
  order; extra members and the world-hash rule; legacy-v1 rule 8 (NaN flows; comparisons cost 0).
  Also in 0.2: an `Edge` may carry a parameter `name`; a given layer-0 object's `valid`/`canon`
  may be a host rule `{"host": "module:qualname", "digest": sha256}`; tags may be written as a
  `{field: sort}` mapping (`{"items": sort}` is a variable-length tag); recursion mode `none`.
