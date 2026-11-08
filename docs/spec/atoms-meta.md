# Opulse atoms-meta: programs as objects (specification)

Spec version: `atoms-meta/0.3` (2026-11-05). Status: binding interface for the meta work
(package `opulse.meta`). It extends `docs/spec/atoms-v2.md` (atoms-v2/0.2) and replaces its
section 16 item "definitions or programs as objects". Every rule of atoms-v2 still holds unless
this file says otherwise. Words used with a fixed meaning: **must**, **must not**, **may**.

Notation is ASCII only (objects `Code<...>`, operations `eval(c, xs)`, combinators `@name[f]`,
observations `?name{x}`).

## 1. Summary

Four things are added. Each is an ordinary use of the six kinds of atoms-v2 0.4 (object, operation,
combinator, observation, law `#`, bridge `~`) and of templates; no new kind is added.

| part | what it is | kinds used |
|---|---|---|
| Code objects | `Code<...>`: values whose contents are definition trees in canonical form (all six kinds and templates); `eval` and `run` execute them with fuel | object, operation |
| Identity | every definition has a content hash; evidence and promotion attach to the hash | (library rule) |
| Self-modifying machine | world `vonneumann`: program bytes live in memory; stores may change the code being run | all six |
| Interpreters, compilers, world building | worlds `compiler` (the compiler is the bridge `~compile`) and `builder`; `World<...>` values with a well-formedness check | all six |
| Generator programs | level 3: programs and templates that produce definitions of any kind (section 7) | all six |

The four invariants of atoms-v2 section 11 hold for all of them (section 9).

## 2. Code objects

### 2.1 Sorts

`code` is a given compose object (not sealed) of every meta world that handles definitions as values (`code`, `compiler`, `builder`; `vonneumann` stores programs as bytes, not as code values). These worlds declare it with one shared declaration (`opulse.meta.code_world`), so the sort, its entry rule and the operations of 2.3 are identical in all of them. Its values are cards (atoms-v2
2.1). Display name: `Code`.

```text
code  = def(kind: str, sig: sig, body: expr, atoms: list, deps: list)
sig   = op(inputs: list, output: edge)           -- kind "operation"; edge = edge(sort: str, enter: str)
      | comb(arity: int, op_params: list)         -- kind "combinator"; op_params: positions (int)
      | obs(reads: list)                          -- kind "observation"; reads: probe names (str)
      | const()                                   -- kind "object", form "constant"
      | law(vars: list)                           -- kind "law"; var(name: str, sort: str)
      | bridge(source: str, target: str, interface: list, domain: opt)
                                                -- kind "bridge"; pair(src_op: str, tgt_op: str)
      | template(params: list, produces: str)     -- kind "template"; param(name: str, kind_or_sort: str)
expr  = var(name: str) | lit(value) | fn(name: str)
      | call(fn: str, args: list)
      | let(name: str, value: expr, body: expr)
      | case(arms: list, default: opt)            -- arms: list of arm(cond: cond, body: expr)
      | rec(fn: str, params: list, body: expr, args: list, measure: measure [, memo: bool])
      | blocks(vars: list, entry: str, blocks: list)
cond  = test(expr: expr) | and(l: cond, r: cond) | or(l: cond, r: cond) | not(c: cond) | always()
measure = fuel() | legacy() | node(expr: expr)
opt   = none() | some(value: expr)
bind  = bind(name: str, value: expr)              -- Blocks vars and assignments
block = block(label: str, assigns: list, end: end)
end   = jump(target: str) | cjump(cond: cond, then: str, else: str) | halt(value: expr)
atom  = atom(name: str, digest: str)
pattern = template(pattern: pattern, fallback: pattern) -- template body, not an expr
        | node(expr) | map(list of entry(key, pattern)) | list(list) | tuple(list)
        | value(value) | bool(bool card) | bottom(reason: str) | none()
        | definition(name: str, kind: str, content_hash: str)
origin = template(template_code: code, args: list of pattern) -- instantiation provenance in deps
```

- `list` is the native sequence sort: one tag `items` with variable fields (atoms-v2 4.1).
- The card sort of each value is its line name (`code`, `sig`, `expr`, `cond`, `measure`, `opt`,
  `bind`, `block`, `end`, `edge`, `atom`, `list`). Tags are the names before the parentheses.
- `expr` mirrors the kernel nodes (atoms-v2 6.1) one to one. `fn(name)` is the literal operation
  reference (`kernel.FnRef`). `Lit` values are stored as values (int, str, card); host booleans
  are stored as `bool` cards and restored to host booleans on decoding. A literal that was
  already a `bool` card uses `literal.bool_card` so it decodes as a card instead. A declared-failure
  `Lit(Bottom(reason))` inside a template pattern uses a dedicated `literal.bottom` card, never
  a value of another sort; `literal.tuple` and `literal.perm` encode core-supported tuple and
  permutation literals. `pattern.bottom` is available for standalone fallback patterns.
- The optional `rec` memo field is the host boolean `True`, not a `bool` card. Omission
  means `False` and retains the existing five-field plain recursion form and its hash.
  Quote, canonicalize, decode and inline preserve both forms; memoized recursion hashes differ.
- Objects of form `refine` or `compose`, including outputs of templates, and observations with
  memory have no `code` form. A refine/compose template output is stored as its core `Definition`
  plus `origin = template(template_code: code, args: list of pattern)`; each argument is encoded
  with `encode_pattern` in the canonical template parameter order (section 7). The provenance
  card is not itself a code dependency and cannot be passed to `code_hash`.
- `law` has a boolean statement over typed variables and decodes to a kernel definition with
  those variables as arguments. `bridge` stores its map as body and its optional domain in its
  signature; decoding wraps the map in the core partial-bridge `Case` with
  `Bottom(outside_domain)` as default. `template` stores the produced spec's exact pattern and
  fallback body as typed cards, including `$param` placeholders and kernel nodes. Template code
  decodes to a placeholder kernel record but `eval` rejects it as `Bottom(not_callable)`.
  `instantiate_code(template, args)` uses core template
  substitution, then quotes a callable produced body; for noncallable object forms it returns
  the produced definition with its origin card instead of a code value.
  Core-inserted `_template_ref_<i>` bindings are part of that body: they cite the template
  and applicable definition arguments as literal operation references. They remain in the
  canonical body and dependency closure, and so preserve core execution and charged steps.

### 2.2 Canonical form

`quote` (section 2.4) and the entry rule of `code` produce the canonical form. A code value is
canonical when all of these hold:

The notation for each expression in `Code<...>`, including a bridge domain, uses the core
expression printer when its text round-trips to the same node; otherwise it uses the lossless
meta expression form.

1. Parameters are named `x0, x1, ...` in order.
   Law variables and template placeholder names follow the same renaming rule; sorts and kinds
   remain attached to their positions. Bridge map and domain both bind `x0`.
2. Bound names are renamed in the order in which a left-to-right preorder walk meets their
   binder: `Let` names and `Rec`/`Blocks` parameters and variables become `v0, v1, ...`; `Rec`
   function names become `r0, r1, ...`; block labels become `l0, l1, ...` (the entry label first).
   A generated `v<i>` or `r<i>` already used by a resolved given call is skipped. `Blocks`
   initializers are renamed sequentially: each initializer sees only the preceding bindings;
   block bodies see every block variable.
3. A call of an invented definition is written `call("#<hash>", args)` where `<hash>` is that
   definition's content hash (section 3). A call of a given atom keeps the atom name. A call of an
   operation parameter keeps the parameter name (`x<i>`). Resolve a call by local `Rec` function,
   then a lexical variable if no global entity has that name, then a globally resolved atom or
   dependency. A lexical variable that also resolves globally is ambiguous and cannot be quoted.
   The `atoms` list must not contain any parameter or bound name, whether or not that atom
   is called in the root body; generated lexical names must also remain disjoint from atoms.
   Given names shaped exactly like `#` followed by 64 lowercase hex digits are forbidden; other
   `#`-prefixed names are ordinary given names. Recanonicalizing a produced code value preserves
   its exact value, including its atom and dependency metadata.
4. `deps` lists the code value of every invented definition in the dependency closure, each
   canonical, sorted by hash, no repeats. `atoms` lists every given atom named by the body or
   a dependency, `atom(name, digest)`, sorted by name; `digest` is section 3.2.
   An instantiated template additionally carries a terminal `origin.template` card with the
   canonical template code and ordered arguments. Definition arguments record their name, kind
   and content hash; primitive arguments record their value. The entry rule reinstantiates the
   template and arguments, resolves invented calls in the produced body against the corresponding
   hash references in the canonical body, and rejects a mismatch in kind, signature, body or
   dependencies. Name-to-hash matching is only used to recover resolution: the entire resulting
   canonical body and dependency closure must still match. A
   template pattern and fallback must decode, and its produced spec must be valid, at entry.
   The `origin` card participates in the
   content hash but is not a callable dependency. No evidence is inherited from the template.
5. Values inside `lit` are canonical values of their sorts.

Kernel equality on `code` is structural on the canonical form (`equality: canonical`). Two
definitions that differ only in bound names, in their own name, or in the names of their
dependencies are equal. Equality never decides behaviour: "do these two programs compute the
same function" is a task question, answered by a recorded check (section 3.4).

### 2.3 Operations on code (given, layer 0, in every meta world)

| operation | rule | errors | cost |
|---|---|---|---|
| constructors and accessors of every tag above | compose interface (atoms-v2 4.1) | `invalid` | 1 |
| `tag_of(v)` | the tag name of a card, as text | `invalid` (not a card) | 1 |
| `code_hash(c)` | the content hash of `c`, as text | none | 1 |
| `eval(c, xs)` | section 2.5 | `arity`, `ill_formed`, `foreign_code`, `not_callable`, and every reason of the program | 0 + inner steps |
| `run(c, xs, budget)` | section 2.6 | `arity`, `ill_formed`, `foreign_code`, `not_callable` | 0 + inner steps |

Every invented `code` value built with constructors is put in canonical form on entry (entry rule
`normalize`, `canon_cost: free`, part of the world version). The derived structural fold of `expr`
(user decision 11-04 20:45, item 4) is available, so program transformers can be written as
ordinary invented operations without host code.

### 2.4 `quote`

`quote(d)` is a pure host function of the reference implementation, not a runtime operation: it
reads a stored definition record and its dependency records and returns the canonical code value.
In a body, a quoted program is a literal `Lit(code)`. There is no operation that reads the library
at run time; a program's result never depends on what the library contains.

### 2.5 `eval(c, xs)`

- `xs` is a `list` of argument values. The operation positions are the `op_params` of combinator
  code and, for operation code, the parameters its body calls; an argument in an operation
  position that is neither `fn(name)` nor a `code` value is `Bottom(ill_formed)`. An operation
  argument may be either
  `fn(name)` naming a **given atom of the world**, or a canonical `code` value of kind
  `operation`. `fn(name)` naming an invented definition (or any other non-given name) is
  `Bottom(ill_formed)`. For a code argument, `eval` decodes and checks its signature, canonical
  form, dependency closure, opened nodes and atom digests against the world exactly as for the
  main code (`Bottom(ill_formed)` or `Bottom(foreign_code)`). It adds the decoded operation and
  its transitive dependencies to the inner scope under their `#<hash>` names, and binds the
  argument parameter to `FnRef("#<hash>")`. These checks and bindings cost zero steps. The
  helper `quote_args(library, args)` quotes invented operation references in library arguments
  and encodes references to given atoms as `fn(name)`.
- `eval` decodes `c` into a kernel definition and a scope: the world's given atoms plus every
  entry of `c.deps` as a definition named `#<hash>`. Then it evaluates the call of the decoded
  definition on `xs` **in the same evaluation**: the same fuel, step counter, depth counter and
  trace.
- Before running, `eval` checks in order: (1) header and complete signature shape, including
  every `edge(sort: str, enter: str)` and valid entry rule (`Bottom(ill_formed)`); (2) argument
  arity (`Bottom(arity)`); (3) full canonical form, exact dependency closure, name resolution and
  opened node kinds (`Bottom(ill_formed)`); (4) every atom digest in the root and each dependency
  against the world, and root atoms equal the closure union (`Bottom(foreign_code)` for foreign
  digests, `Bottom(ill_formed)` for malformed metadata); (5) callable kind (`Bottom(not_callable)`).
  These checks charge 0. A legacy `eval_atom` built without any atom digest table may reject a
  canonical noncallable kind as `not_callable` without validating its body or atom metadata; it
  cannot run, so this does not authorize execution in an unchecked world.
- The outcome is the outcome of the call: a `Bottom` of the program is the `Bottom` of `eval`;
  running out of fuel is `Unknown(fuel)` of the whole evaluation.
- `eval` itself charges 0 steps. Therefore the **quote/eval law** holds exactly:
  `eval(quote(d), xs)` and `d(xs)` give equal outcomes and equal layer-0 step counts.
  For combinators, the law also holds with invented operation arguments encoded as their code
  values: `eval(quote(comb), [quote(op), x])` equals the library call
  `comb(FnRef(op), x)` in outcome and steps.
- Law and bridge code are callable. For `eval(law_code, xs)`, `xs` binds the law's
  variables in signature order and the result is the evaluated statement instance:
  `Ok(true)`, `Ok(false)`, or the statement's `Bottom`. The variable count is checked by
  preflight (`Bottom(arity)`), and values whose known sort disagrees with a declared
  primitive sort (`int`, `str`, `bool`) are rejected as `Bottom(ill_formed)` at zero steps;
  `any` accepts every sort. A refinement or other custom sort cannot be checked without
  a world declaration and is left to the kernel.
  Quote/eval matches the evaluation of that statement under the same bindings, including
  its exact steps. A core `Library` that cannot call laws with variables directly may
  evaluate `LawSpec.statement` with those bindings for the comparison.
- `eval(bridge_code, [x])` applies the bridge map. For a partial bridge it evaluates
  the domain first; a false domain yields `Bottom(outside_domain)` without evaluating
  the map, exactly as the core bridge's `Case`. The domain test and map charge their
  ordinary layer-0 steps. Quote/eval matches the corresponding core bridge call in
  outcome and steps. Template code is not callable (`Bottom(not_callable)`); it is
  instantiated with the pure `code.instantiate_code` function. A template-origin card
  in an instantiated code's dependencies records provenance, not a callable definition;
  preflight checks callable dependencies without treating that card as a definition.
- Trace: the `eval` call node has kind `operation`, `given: true`, and the inner call tree of the
  decoded definition as its children. Its `steps` are the inner steps.

### 2.6 `run(c, xs, budget)`

`run` is the reflective form with an inner budget. It returns a value of sort `result`:

```text
result = ok(value) | err(reason: str) | out(steps: int)
```

- `ok(v)`: the program returned `v` within `budget` layer-0 steps.
- `err(r)`: the program failed with `Bottom(r)` (as `catch`, atoms-v2 3).
- `out(budget)`: the program needed more than `budget` steps, or more than 1000 nested calls
  below the `run` call. The result is a value; it is a function of `c`, `xs` and `budget` only.
- The steps actually used (at most `budget`) are charged to the outer evaluation. If the outer
  fuel runs out first, the whole evaluation is `Unknown(fuel)` (never `out`). When the budget ends
  exactly where the outer fuel ends, the budget wins (`out`): `run` never takes the step after its
  budget, so the outer fuel is not exceeded.
- The checks of 2.5 return `Bottom` (they are failures of `run`, not of the program).
- Law and bridge code use the same preflight, budget and step rules as other callable
  code. A law's statement failure or a bridge's `outside_domain` is `err` according
  to the outcome rules above; a template always fails preflight with `not_callable`.
  `inline` unfolds a literal law or bridge `eval` only after the full preflight succeeds;
  it preserves both the outcome and exact layer-0 steps.

### 2.7 Kernel hook (request to core)

`eval` and `run` need a **metered atom**: an atom whose function receives a context
`ctx.call(defn, args, scope_extension, budget=None) -> Outcome` that evaluates inside the running
engine (shared steps, fuel, depth and trace frames), and whose own cost is 0. Until core provides
`kernel.Atom(metered=True)`, `opulse.meta.engine` implements it as a local extension of the kernel
engine with the same semantics, and `opulse.meta.engine.inline` unfolds `eval(Lit(c), xs)` into the
decoded body (for I1).

## 3. Identity and evidence

### 3.1 Content hash

`hash(d) = sha256("opulse.code/1\n" + J(quote(d)))` in lowercase hex, where `J` is the JSON of the
code value (`opulse.value/2`, keys sorted, separators `,` and `:`). Because calls to invented
definitions are written as their hashes and `deps` embeds them, the hash covers the canonical body
and the hashes of all dependencies (a Merkle tree). The definition's name is not part of the hash.

### 3.2 Given atoms

`digest(atom) = sha256` of the JSON of its `OperationSpec.to_dict()` without the display-only
members (atoms-v2 12), which includes the host digest. A code value records the digests it was
written against; running it where an atom has another digest is `Bottom(foreign_code)`.

### 3.3 The ledger (`opulse.meta.identity.Ledger`)

The ledger maps `hash -> record` and `name -> hash`.

- A record holds the code value, the world hash, the status, the evidence list and the contract.
  Status, evidence and contract are keyed by `(hash, world_hash)`.
- Its `deps_hash` is SHA256 of the concatenated sorted dependency code hashes in `code.deps`
  (the SHA256 of empty bytes when there are no dependencies). All attached evidence must carry
  this exact commitment. Imports validate the library's own dependency commitment first and
  translate its evidence to the code-hash commitment before attaching it to the ledger record.
- `bind(name, d)` points a name at the hash of `d`. Re-binding a name to a different hash keeps the
  old record unchanged and appends `(name, old_hash, new_hash)` to the name history.
- **Modification creates a new definition.** Any change to the canonical body, the signature or
  any dependency gives a new hash. A new hash starts with status `callable` at most and no
  evidence. Evidence is never copied, moved or inherited between hashes; to get evidence for the
  new hash, verify it again.
- Changes that keep the canonical form (renaming the definition, its parameters, bound variables
  or its dependencies) keep the hash, so they keep the evidence.
- **A promoted record is immutable.** Writing a different body, signature, evidence or contract to
  a promoted `(hash, world_hash)` raises an error. Dependents refer to hashes, so a dependent of a
  promoted definition never changes when a name is re-bound.
- The ledger is consistent with `atoms.library.Library`: `Ledger.from_library(lib)` records every
  stored invented definition under its hash; the library's `evidence.deps_hash` check and the
  ledger's hash check must agree (a test must show this).

### 3.4 Behavioural questions

Two different hashes may compute the same function. The ledger records an equivalence claim only
as evidence on a pair `(hash_a, hash_b)` with method and scope, like any other evidence
(`exhaustive`, `bounded`, `sampled`). An equivalence claim never merges records and never moves
evidence from one hash to the other.

## 4. World `vonneumann` (self-modifying machine)

### 4.1 State and instruction set (`vn/1`)

- Static parameter `n` (memory size) with `n` in {16, 32, 64, 256}. Addresses are `0..n-1`; every
  address computation is `mod n`. Bytes are `0..255`; arithmetic is `mod 256`.
- Objects: `byte = refine int where 0 <= x < 256`; `mem[n]` = list of exactly `n` bytes;
  `vn = vn(pc: int, a: byte, mem: mem[n], halted: bool)` (display `VN<pc=0, a=0, mem=Mem<...>, halted=false>`).
- One instruction is two bytes at `pc` and `pc+1`: opcode `o`, operand `k`.

| o | name | effect (then `pc := pc + 2` unless stated) |
|---|---|---|
| 0 | `HALT` | `halted := true`; `pc` unchanged |
| 1 | `LDI k` | `a := k` |
| 2 | `LD k` | `a := mem[k]` |
| 3 | `ST k` | `mem[k] := a` |
| 4 | `ADD k` | `a := a + mem[k]` |
| 5 | `SUB k` | `a := a - mem[k]` |
| 6 | `JMP k` | `pc := k` |
| 7 | `JZ k` | if `a = 0` then `pc := k` else `pc := pc + 2` |
| 8 | `ADDI k` | `a := a + k` |
| 9..255 | illegal | `Bottom(illegal)` |

There is no index register: walking an array needs a program that rewrites its own operand bytes
(the classic stored-program technique). Code and data share `mem`.

### 4.2 Atoms

- Operations: `step(s) -> vn` (cost 1; fetch, decode, execute one instruction; `step` of a halted
  state returns it unchanged), `is_halted(s) -> bool` (cost 0, role `decide`), `poke(s, k, b)`,
  `peek(s, k)`, `set_a`, `get_a`, `set_pc`, `get_pc` (cost 1).
- Combinators: nodes `Var, Lit, Call, Let, Case, Rec`, recursion `fuel`. The world combinator
  `@exec` is `Rec(r0, (s), Case(test(is_halted(s)) -> s; default r0(step(s))), fuel)`. Layer-0
  steps of a run = number of executed instructions (HALT included).
- Observations: probes `?pc{s}`, `?a{s}`, `?cell{s, k}`, `?halted{s}`; learner channels per task;
  `judge_view: full_state`.

### 4.3 Run report and code identity

`opulse.meta.vn.report(s0, fuel)` runs `@exec` and returns:

- `fetched`: the set of addresses read as instruction bytes (`pc` and `pc+1` of each executed
  instruction);
- `stores`: the list of `(step index, address, old byte, new byte)`;
- `versions`: the code images. Image `C_0` = `mem` of `s0` restricted to `fetched`. Each store at
  an address in `fetched` that changes the byte starts the next image `C_{i+1}`. The identity of an
  image is `I(n, [[address, byte], ...])` with the pairs sorted by address, where
  `I(n, payload) = sha256("opulse.vn/1\n" + str(n) + "\n" + JSON(payload))` (JSON without spaces).
- `self_modifying = len(versions) > 1`; `writes_ahead` (a changed byte is fetched after the store)
  and `writes_behind` (a changed byte was fetched before the store) are recorded separately.
- `outcome`: `Ok(final state)`, `Bottom(illegal)`, or `Unknown(fuel)`.

A **routine** is `(base address, bytes)`; its identity is `I(n, [base, [byte, ...]])`
(`opulse.meta.vn.report.routine_id`). Evidence for a routine is keyed to that identity and covers runs that start with those
bytes at that base. After a run that changed bytes inside the routine, memory holds a different
routine: its identity differs and it has no evidence until verified again. A contract of a
routine must list every address it may change, including its own code bytes.

Tasks may ask: Compute (final `a` or state under fuel), Decide (`self_modifying` within fuel `N`;
"Unknown(fuel)" is never a correct answer, so Decide tasks are generated only where the run halts
within `N` or provably loops on a repeated full state), Invert (which input byte or which code byte
gives a target result).

## 5. Interpreters and compilers (world `compiler`)

- **Source language** `tiny/1`: definitions of the integer world (`integer@2`) restricted to the
  operations `add`, `sub`, `is_zero` and the nodes `Var, Lit, Call, Let, Case, Rec(measure fuel)`,
  plus calls to other `tiny` definitions. Values are ints; a source run whose result is outside
  `0..255` is a validation case with expected outcome `Bottom(overflow)`.
- **Target**: `vonneumann` programs, `prog = prog(n: int, code: list, args: list, out: str)`:
  code bytes loaded at address 0; `args[i]` is the address that receives argument `i`; the result
  is `a` at `HALT` (`out = "a"`).
- **Interpreter as a definition**: `vn_interp(code, args, fuel)` is an invented operation of the
  integer world written in kernel nodes (no host code). It executes `vn/1` on list values. Its
  evidence: for every program in a recorded finite family and every input in scope, its result
  equals `opulse.meta.vn` (exact outcome, including `Bottom(illegal)`; inner exhaustion is compared
  as `out`).
- **Compiler as a definition**: `compile(c) -> prog` takes a `code` value of `tiny/1`. The
  reference compiler in `opulse.meta.compiler` (host, untrusted tooling) covers all of `tiny/1`.
  A learner compiler is an invented operation built with the derived fold of `expr`.
- **The compiler is a bridge** (common.md "Six kinds"): `bridge ~compile: Code -> Prog`, partial,
  with domain `tiny/1`. Its commuting check is translation validation: run the source, or compile
  and then run the program; both paths must give the same outcome on the recorded scope.
- **Translation validation**: a compiled pair `(source hash, prog identity)` is accepted for a
  scope when, for every input in the scope, `run(prog)` equals the source outcome (value, or
  exact `Bottom` reason; full final machine state where the task declares it). A source
  `Bottom(r)` requires target `Bottom(r)`; since the machine only fails with `Bottom(illegal)`,
  non-`illegal` source failures cannot be validated against an illegal opcode. The reference
  compiler rejects source constructs it could only encode as an illegal opcode (including a
  `Case` without a default). The evidence attaches
  to the pair, not to the compiler. A compiler (a definition) gets evidence by translation
  validation over a recorded finite family of source programs (for example all `tiny` bodies up
  to 5 nodes over `x0, x1` and literals `0..3`) times an input scope; the method is `bounded`
  (or `sampled`, then not promotable).

## 6. World building (world `builder`)

### 6.1 `World<...>` values

A world declaration is a value of sort `world`:

```text
world = world(name: str, version: int, sorts: list, ops: list, nodes: list, recursion: str,
              probes: list, judge_view: str, open_kinds: list, tags: list [, laws: list])
                                       -- laws: optional 11th field, present only when non-empty
sort  = enum(name: str, tags: list) | range(name: str, lo: int, hi: int)
op    = table(name: str, role: str, inputs: list, output: str, errors: list, rows: list, cost: int)
      | body(name: str, code: code)
row   = row(inputs: list, out: cell)          cell = val(value) | err(reason: str)
```

A built world has no host code: given operations are finite tables (atoms-v2 5, `impl: {table}`)
or code bodies over earlier operations.

### 6.2 Well-formedness

`wf(w) -> report` returns `ok()` or `bad(check: str, detail: str)` for the first failed check, in
this order:

1. `names`: sort, op and probe names are unique and valid identifiers.
2. `sorts`: every sort is finite (`enum` with at least one tag, `range` with `lo <= hi`, at most
   256 values); every sort an op or probe names exists (`int` and `bool` are built in).
3. `tables`: every table is total on the product of its input sorts (exactly one row per input
   tuple), every `val` is in the output sort, every `err` reason is listed in `errors`; the product
   has at most 4096 tuples.
4. `bodies`: every body code type-checks against the earlier ops (no forward references, no host
   code, only the listed nodes), and terminates on the finite input product within 10 000 steps
   per input (checked exhaustively).
5. `laws`: every declared law (an optional list in the world value: a law code value over the
   world's sorts, section 2.1) is `Ok(true)` on every tuple of its finite variable product; the
   first failing tuple is the detail of `bad("laws", ...)`.
6. `probes`: every probe names an op of role `decide` or `transform` that is not of role `act`,
   and no probe depends on an `act` op.
7. `kinds`: `open_kinds` is a non-empty subset of the six kinds of atoms-v2 0.4; `nodes` and `recursion` follow
   atoms-v2 12; `judge_view` is `full_state` (this world-value schema has no projections).
8. `tags`: tags follow common.md "World tags".

`instantiate(w)` turns an accepted world into a `WorldDecl` (dialect `atoms-v2`) plus kernel
atoms. The world hash of the instance is the content hash of the canonical `world` value. A world
that fails `wf` cannot be instantiated.

### 6.3 Derived worlds

`extend(w, c)` adds the code `c` as a new layer-k atom of `w` only when the ledger holds promoted
evidence for `(hash(c), world_hash(w))`; the result lists the scope and contract of `c`
(atoms-v2 12, derived world). Evidence from one world never applies in another world with a
different hash.

## 7. Generator programs (level 3)

Templates (common.md "Definition templates in v1") are core records. A **generator program** is the
meta level above them: an ordinary invented operation whose result is a `code` value (a program
transformer such as `const_fold`, a compiler, a specializer, a template expander written in kernel
nodes).

- A generator program is verified like any operation, as a function from code to code (for
  example semantic preservation on a recorded family of input programs). Its evidence attaches to
  its own hash.
- Every code value it produces is a new definition: it enters the pipeline under its own hash,
  with no evidence, and must be verified on its own scope before it is promoted. The generator's
  evidence may be cited only for outputs whose inputs lie in the generator's recorded family, and
  never replaces the output's own unfold-equivalence check.
- An output records its producer in the ledger record, not in the core definition's executable
  dependencies: `produced_by: [generator code hash, run input hashes]`. A code input uses its
  code hash; a non-code input uses the hash of its encoded value. This rule also applies when the
  generator returns a template-instantiation request. The template code and ordered arguments
  live separately in the output's `origin.template` card (or in the core-only provenance record),
  never in place of the actual generator and its run inputs. A boundary can show
  "specialize(poly, 3)" as one step or open it into the produced body.
- Kinds: the code-card codec quotes laws, bridges and templates as well as operations,
  combinators, observations and object constants. `instantiate_code` returns code for core
  template instantiations that produce callable bodies; it records the template code and all
  argument values in `deps` provenance. Each resulting code hash is a new definition identity;
  it carries no evidence from its template. The runtime `eval` hook for law and bridge kinds
  is implemented (section 2.5); templates are never callable by `eval`.
- A callable template output uses the same canonical `code` value when written and recorded:
  `quote_from_library` of the stored definition equals the ledger's code, including the
  `origin.template` card in `code.deps`. The ledger dependency commitment (section 3.3) hashes
  only dependency code entries, including the template's executable reference when core inserts
  `_template_ref_<i>` bindings; the origin card is provenance and is not part of it. The origin
  (template code and argument values) does enter the output's code hash, so identity covers
  template + arguments. A `refine` or `compose` output instead has no code form: the ledger stores
  its core `Definition` with the separate `origin.template` card (section 2.1), and its pipeline
  state remains that of the core definition. Neither kind borrows its template's evidence.
  Direct code outputs carrying an `origin.template` must resolve and reconstruct that template
  and its arguments against the library before storage. Every quotable output, direct or requested,
  must equal `quote_from_library` of its stored definition before ledger insertion. Inserting or
  importing a core-only provenance record must validate its canonical origin and reconstruct its
  kind, spec, body and dependencies from the embedded template and ordered arguments; a claimed
  argument that does not produce the stored definition is rejected.
- Generated observation code enters the core observation check and callable pipeline, including
  probe-grant checks; the generator supplies a truth-state sample for the callable check. Generated
  template code enters the core `check_template` and callable pipeline. Neither bypasses core
  checks, and templates remain noncallable by `eval`.
- A bounded family requires every independently verified member to have bounded or exhaustive
  evidence for its own request scope. If any member is sampled, the family evidence is sampled,
  regardless of the requested family method, and cannot be promoted. To cite a family, first
  reconstruct the member from the cited template and argument mapping, and compare its body,
  spec and dependencies with the candidate; matching mutable metadata alone is insufficient.
  The core template citation and verification APIs must enforce the same rules independently of
  this meta helper.

## 8. Showcase worlds

Each meta world (`code`, `vonneumann`, `compiler`, `builder`) provides, in English and ASCII:

- a declaration `worlds/decl/meta/<world>@1.json` (`opulse.world/2`, loads through
  `WorldDecl.from_dict`), with `tags` as in common.md "World tags";
- a creation story: at least 6 invented definitions over at least 5 layers, covering at least
  three kinds, every one verified through the library or the ledger, promoted only with
  `exhaustive` or `bounded` evidence;
- a 5-level difficulty ladder (`level`, `knobs`, `what_changes`);
- 3 hard showcase tasks, including one Invert and one Decide, each with `prompt`, `answer`,
  `why_hard`, `check`, and an exact test that recomputes the answer;
- an export `docs/assets/data/meta/<world>.json` in the shape `opulse.world_v2_export/1` plus
  `tags`, `ladder`, `showcase`.

Module protocol (checked by `python -m opulse.meta.check`):

- `opulse.meta.worlds.<world>.world.declaration() -> WorldDecl` builds the declaration fresh,
  with host digests computed from the current host source; the committed decl file equals
  `declaration().to_dict()` exactly.
- `opulse.meta.worlds.<world>.export.build_export() -> dict` builds the export fresh;
  `export.write()` writes the decl file and the export. The committed export equals
  `build_export()` exactly.
- A showcase entry has the keys `angle` (`Compute`, `Invert`, `Decide`, `Describe`, `Induce`,
  `Create`), `kinds_involved`, `prompt`, `answer`, `why_hard`, `check`. A prompt states every fact
  needed to compute the answer (for `vonneumann`: every memory cell that is not zero, and the rule
  "all other cells are 0"; the program bytes, not only a source to be compiled by unstated tooling).
- Every story entry has `definition` (one or two English sentences) and at least one example that
  shows what the entry adds; two entries do not share the same example.
- `ascii` fields: every story entry and every example carries the exact ASCII source. Declarations
  use core notation (atoms-v2 18.5); when a declaration names meta sorts that core notation does not
  print (`code`, `vn`, `world`, qualified `world@version:sort`), `opulse.meta.export_util` prints the
  same head (`obj`, `op`, `comb`, `obs`, `law`, `bridge`, `template`) with the meta sort names and the
  meta value forms `Code<...>`, `VN<...>`, `World<...>` (section 2, `opulse.meta.notation`) as
  literals. Every `ascii` text must parse back to the exported definition or call; placeholder
  bodies or display-only text are not allowed. the strict mode of `python -m opulse.meta.check` (`opulse.meta.check.check(strict=True)`) enforces this.
  An example may store an `Ok` result as `{"kind": "Ok", "code_hash": h}` instead of
  duplicating a large code card. Its ASCII result must parse as a complete code value
  whose canonical `code_hash` is exactly `h`; a displayed projection is not sufficient.
  Template exports preserve a richer verified pattern either in `spec.pattern` or in
  `runtime_spec`, publish the parsed ASCII pattern in `source_pattern` when the two
  representations differ, and bind the parsed signature to `source_spec_hash`. Strict checking verifies
  both the published body and that source hash. Long enumerated evidence/cost domains
  may be represented as `{count, sha256}` while the verifier retains its full inputs.
- Evidence objects are immutable once recorded: a verifier stores its own copy (enumerated inputs or a
  domain fingerprint, the size it counted) and returns copies; prose never stands in for an
  enumerated domain.

## 9. The four invariants

| invariant | how it holds | required test |
|---|---|---|
| I1 always unfoldable | `eval(Lit(c), xs)` unfolds to the decoded body; `step` is a layer-0 atom, so a machine run unfolds to its instructions; a compiled program unfolds to machine steps | for every stored meta definition: `Boundary()` evaluation equals the full unfolding (outcome and steps); quote/eval law on every story definition |
| I2 boundary never changes a result | `eval` and `run` charge exactly the inner layer-0 steps and splice the inner trace | random code values x random boundaries: equal outcome and steps; flattened views splice |
| I3 observation never changes facts | `quote` and `code_hash` read records and change nothing; machine probes read the state; `self_modifying` is judged from the full run report | probes and `?` definitions leave the state unchanged; two learner views give the same verdict |
| I4 promotion carries scope and contract | evidence is keyed to `(hash, world_hash)`; modification gives a new hash without evidence; promoted records are immutable; routine contracts list self-changed addresses; compiled pairs carry their validation scope | promoting a modified program fails; a re-bound name leaves dependents on the old hash; editing a promoted record raises |

**Scope of use.** The evidence of a promoted definition covers its own scope through its full
unfolding; it never extends the scope of a callee. When an example calls a promoted callee on an
input outside the callee's recorded scope, the export marks that call (`outside_scope: true` in the
trace node or the example); a boundary may still show it as one step, but the mark must stay.

## 10. Out of scope (documented limits)

- Reflection on the running evaluation: no operation reads the current frame, the trace, the fuel
  left, or the library at run time.
- Unbounded towers: every interpreter level charges its steps to the same fuel, so a tower of
  interpreters is finite for every finite fuel. Fixed points of `quote` (a program that contains
  its own hash) do not exist by construction.
- Infinite objects (streams), and code forms for refine/compose objects and observations with
  memory (laws, bridges and templates have code forms since 0.4; section 2.1).
- Self-modification in `Blocks` programs of other worlds: only `vonneumann` stores code in data.

## 11. Reference implementation

| module | contents |
|---|---|
| `opulse.meta.code` | code card encoding, `quote`, `decode`, canonical form, `code_hash`, atom digests |
| `opulse.meta.identity` | `Ledger` (section 3.3), `from_library` |
| `opulse.meta.engine` | metered atoms, `eval`, `run`, `inline` (until core provides the hook) |
| `opulse.meta.vn` | `vn/1` machine, assembler and disassembler (ASCII), `report` |
| `opulse.meta.compiler` | `tiny/1` reference compiler, translation validation |
| `opulse.meta.builder` | `world` values, `wf`, `instantiate`, `extend` |
| `opulse.meta.notation` | ASCII printer and parser for code, machine and world values |
| `opulse.meta.gen_code` | seeded random code values for the invariant tests |
| `opulse.meta.worlds.<world>` | declarations, hosts, stories, ladders, showcases, exports |

### Changes

- `atoms-meta/0.1` (2026-11-04): first version.
- `atoms-meta/0.2` (2026-11-04): exact vn identity encoding (4.3); `run` budget wins a tie with the
  outer fuel (2.6); the compiler as a bridge (5); generator programs (7); sections renumbered.
- `atoms-meta/0.3` (2026-11-05): based on core spec 0.3. Canonical form refuses ambiguous call
  names and hash-shaped given names; Blocks initializers are canonicalized in order (2.2). `eval`
  preflight order, operation positions (combinator `op_params`, or the parameters an operation's
  body calls), code-valued operation arguments with arity checks (2.5). Nested `run` budgets: the run
  whose own deadline is hit reports `out`, the innermost run owns a tie (2.6). Ledger dependency
  commitments and evidence snapshots on every import path (3.3). Translation validation compares
  Bottom reasons exactly (5). `judge_view` of a built world is `full_state` (6.2). The `code` sort
  is declared once (`opulse.meta.code_world`) in the worlds that handle code values (2.1). Module
  protocol, self-contained prompts, immutable evidence and distinct examples (8); scope of use (9).
