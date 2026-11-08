# compiler@1

Layer 0 imports the integer/list primitives of `compiler.interp` and adds
`result_a`, `fail_mismatch`, and `run_prog`. The latter is a metered, given
adapter: each vn/1 instruction, including HALT and illegal instructions,
charges exactly one layer-0 step. It returns `result.ok(a, mem)`,
`result.err(illegal)`, or `result.out(fuel)`. The world opens fuel recursion to
accommodate tiny/1 tail recursion; the preexisting measured `vn_interp` also
runs in this world. An outer budget below the executed instruction count
returns `Unknown(fuel)` with exactly the steps it could pay for.

The interpreter tower is `fetch` and `exec_one` at layer 1, then `vn_interp`
at layer 2. A canonical constant stores the tiny/1 exact-integer iterative
Fibonacci source. The reference `~compile: Code -> Prog` bridge is untrusted
tooling for recursive tiny/1, and its output is a separate immutable program
constant. The promoted invented `~compile` below handles a bounded nonrecursive
subset; it cannot compile this Fibonacci recurrence.
The program constant records the source hash in `produced_by`; this is
provenance, not correctness evidence. Translation validation checks only the
ordered `(source_hash, full_prog_hash)` pair on x0=0..13 at fuel 500; the
routine identity is separate. Pair evidence lives in the identity ledger.
The named source and program constants have only literal-unfolding evidence
in the identity ledger. Source and machine agree on all 14 accepted inputs;
fib(13)=233. At n=14, the exact source produces `Bottom(overflow)`, while
the machine returns `Ok(121)` after 291 instructions. At n=15, the machine
returns `Ok(98)` after 311 instructions. Neither input belongs to the pair's
accepted scope.

`source_fib` computes the recurrence as a kernel `Rec`, `target_fib` loads
the compiled image into invented `vn_interp`, and `@validated[f,g]` compares
the two operations on its explicitly verified family. `fib_crosscheck`
computes and compares the two semantics; `fib_recurrence` checks three
neighboring crosschecked values against the recurrence. Every invented
definition goes through the library write/check/callable/verify/account/
promote pipeline. The 14-input source, 14-input target, two-input
combinator, 11-input crosscheck, and two-input recurrence scopes are
separate bounded evidence, not universal proofs. Three-way checks on n=0..13
also compare the source, the invented interpreter, and the reference machine
and metered adapter. At n=10 all return 55: 31 source layer-0 steps, 211
machine instructions, 211 metered steps, and 5232 interpreter layer-0 steps.
The 256-literal inversion exhaustively validates the discounted-order
balance template on 16 inputs (x0=0..15), accepting only rates 15..32.
The `agrees` operation is the result-channel checker: the atoms-v2
observation interface probes robot truth state rather than an arbitrary
`result` card, so an observation would claim a probe the world cannot supply.

A separate countdown predicate checks whether `x0-255-1` is zero. At x0=0,
the exact intermediate is negative: the source returns `Ok(0)` in 3 steps,
the byte program returns `Ok(1)` in 7 instructions, and the rejected pair
stays unpromoted. Every machine result in this rejected 16-input scope is
a byte. The program constants are literal objects; the tiny/1 source code
has distinct given-atom digests from this compiler world and directly
evaluating the nested code under this world returns `Bottom(foreign_code)`.

Quoted `@validated` has only its statically called `agrees` in `c.deps`.
`eval(c, [fn(list_len), fn(list_len), [4,5]])` succeeds with `Ok(2)` in 3
steps because `list_len` is a world atom. But passing invented
`fn(source_fib)` and `fn(target_fib)` yields `Bottom(ill_formed)` in 0
steps: neither operation is in that quoted code's dependencies. The library
call works because it uses the library scope, not the closed `eval` scope.
To evaluate an invented operation argument, its quoted code hash must be
present in the combinator code's dependencies and passed as `fn(#hash)`;
the current generic quotation does not capture operation arguments in deps.
This limitation does not weaken any of the recorded pair evidence.

The invented kernel-node `lcompile` belongs to the separate learner compiler
world. This story promotes it with bounded translation validation of the same
4618-program family used by `learner.validate_family`: 3325 accepted programs
on all 256 input pairs (x0,x1) in 0..15, with 1293 rejected programs excluded
from promotion. The five helpers have separately verified bounded evidence
over distinct actual call arguments collected during that family run; each
scope records its distinct-input count, total call count, and domain fingerprint.
Each helper checks that its stored kernel scope matches the corresponding
subset of the original scope before
reusing the direct run as the reference; every distinct argument still checks
its exact outcome and step count against the fully inlined kernel body.
Zero-cost capture atoms are temporary verification tooling, not part of the
stored invented bodies or the learner world. The story's case program is
outside the family, explicitly marked `outside_scope` in its compiler example;
its separately validated pair does not inherit compiler-family evidence. Its output is
stored with `produced_by=(lcompile hash, source hash)` and validated separately
on (x0,3) for x0=0..15. This pair's evidence is distinct from the full
compiler family's evidence.
The core `BridgeSpec` named `compile` uses the learner compiler's invented
`lcompile` as its map, followed by a given byte-program packer. Its source
and target sorts are `compiler@1:code` and `compiler@1:prog`. The domain is
an exact kernel-node membership test on 16 accepted family hashes (including a variable,
an addition, a subtraction, and a let expression).
The core bridge verifier checks 16 commuting interface pairs, with x0 and x1
in 0..3: 256 checks in total, 16 codes, no skipped inputs.
The bridge evidence is bounded and promoted in a separate compiler verification
library with its own world hash. It does not extend the Fibonacci reference
pair's scope or promote the bridge for all 3325 accepted family members.
The given source and target evaluators return the result channel, not full
machine memory. `Compiled[src]` is a verified core `TemplateSpec` instantiated
through `meta.generators.instantiate_family` on one recorded source operation;
the member has its own verified (not inherited) bounded evidence. The template
and member remain verified, not promoted.
`#interp_agrees` is bounded to inputs 0..13 and replays one rewrite from
`source_fib(0)` to `target_fib(0)` with the target's exact layer-0 steps. The proposed
`#fib_commutes` remains callable, never promoted: x0=14 yields source 377
versus target 121, and x0=15 yields source 610 versus target 98.
Interpreter evidence includes the loaded Fibonacci programs on x0=0..13;
crosscheck evidence includes inputs 0..10, covering recurrence at x0=8.
The world now uses the core metered atom from `meta.engine` directly; the local
hash adapter is removed. Core requests: a verifier
for closed constant objects, a non-robot result-channel observation, and an
explicit operation-argument closure mechanism for quoting combinators.
The exported `ascii` declarations are parsed compact views; when a kernel body
cannot be printed and parsed by the core notation, the view uses
`fail("see_json_body")` rather than claiming to encode that body. The exact
kernel body, result and evidence remain in `body`, `examples` and `evidence`.
The four closed constants and the template member have display aliases because
core notation requires uppercase object and lowercase operation names. The
ASCII value display capitalizes internal card sorts; `Encoded` wraps the exact
JSON value when a card tag cannot be printed by core notation.
