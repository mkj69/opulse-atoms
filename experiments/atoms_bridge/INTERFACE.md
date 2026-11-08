# Bridge experiment interface

Bridge analysis uses `atoms_mul.analysis.decision` for shared bootstrap,
eligibility and decision rules (multiplication INTERFACE section 7). The
shared runner provides checkpoint fingerprints and prompt cost accounting.

`atoms_bridge` depends on `opulse.atoms.bridges.BridgeContext`, `check_bridge`,
`verify_bridge`, the core Library and kernel, and the shared `atoms_mul` Track,
summary and analysis. The source is `atoms_mul_B` as declared by the integer
experiment; the target is `computer@1`. No new evaluator may simulate a
cross-world call. The machine state and instruction semantics come from
`opulse.worlds_v2.computer`.

Learner syntax extends MASM with exactly one instruction, `xcall mul r1, r2
-> r0`. It reads the two byte registers, calls `~to_nat` on each, invokes the
integer-world `mul` (saved in G2, given in G3), calls `wrap_byte` on the
natural result, calls `~to_byte`, and writes r0. Other registers, flags and
memory must remain unchanged by this instruction. `xcall` cannot name any
other operation or use another destination. Source calls share the enclosing
core kernel fuel and exact layer-0 step counter. It is not a given machine
`mul` instruction. Groups G1/G2/G3 map to shared Track groups A/B/C.
The separate display-only `boundary_steps` treats each saved integer `mul`
invocation as one step; charged `steps` and fuel always include its unfolding.

G2's saved `mul` is exhaustively verified on 0..255 x 0..20. The `xcall`
checks both arguments against that scope before invoking G2 `mul` and
refuses out-of-scope calls with `Bottom(outside_domain)`. G3 calls its given
`mul` without this saved-definition restriction.
The verified bridge permits only the recorded scope; failing domain entries
return `Bottom(outside_domain)`. A given source `mul` is not a promoted saved
definition: both return equal bytes but their costs differ. Programs with
invalid syntax or access to an unavailable bridge are rejected by the checker,
not interpreted as successful answers.

Runtime resolution limitation: `Library.attach_world` and `BridgeContext`
resolve bridge verification by side, but `Library.scope()` is a flat kernel
scope at runtime. On `machine.scope()`, machine `add` (arity 3) shadows
integer `add` (arity 2), and machine `is_zero` (arity 2) shadows integer
`is_zero` (arity 1). Calling attached integer `mul(9, 6)` through that
scope raises `TypeError`; the executable minimal reproduction is
`test_core_cross_world_scope_collision_reproduction` (expected failure).
`run_sub` starts with `integer.scope()` for the core's attached-world
fallbacks. Until core provides contextual resolution at runtime, it retains
only local collision aliases (`machine_add`, `machine_is_zero`) for MASM,
then runs both worlds under one core kernel layer-0 counter for steps and
fuel. Core bridge checking, verification and evaluation remain in use.

The entry point is `sub main:`. For example:

```text
sub main:
  xcall mul r1, r2 -> r0
end
```

Offline command (from repository root; include both experiment packages in
`PYTHONPATH` until project test configuration includes this package):

```sh
PYTHONPATH=src:experiments/atoms_bridge:experiments/atoms_mul python -m atoms_bridge.run --policy transfer --groups A,B,C --episodes 2 --run-id dryrun --out experiments/atoms_bridge/runs
```

Real command: **requires supervisor approval; do not run**.

```sh
PYTHONPATH=src:experiments/atoms_bridge:experiments/atoms_mul python -m atoms_bridge.run --policy llm --allow-api --model MODEL_APPROVED_BY_SUPERVISOR --groups A,B,C --episodes 40 --run-id real --out experiments/atoms_bridge/runs
```
