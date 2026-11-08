# code@1

Layer 0 provides integers (add, sub, mul, div, is_zero, eq, lt), card and list
construction/access, strings, card-tree size, and code_hash. eval and run are
given metered core Atom subclasses from opulse.meta.engine; their inner calls
share outer fuel, steps and traces. The world-local Library.run adapter uses
engine.call to preserve nested budget ties and the 1000-call run limit.
No invented definition contains host code. The recursive const_fold visitor uses
the kernel memo combination mode (Rec with memo=True); the layer-0 cost of each
transform and its plain unfolding remain available separately.

The additional law #fold_idempotent checks all 224 recorded code values, and its
promoted equation replays as one rewrite step. The near-miss #unsafe_equivalence
fails on the strict-division counterexample and remains callable only; the
export records its exact program, input, Bottom(div_zero) and Ok(0).
The ~fold_bridge map commutes with const_fold on all 224 code values; both
paths are also checked on inputs 0..6 (1568 program-input cases).
Specialize[k] verifies k=0 and k=3 as a bounded template family, then records
each produced operation with independent evidence. A separate run_generator
output records produced_by; no evidence is transferred to generated code.
Direct eval on unchanged quoted template members matches their library run,
including outcomes and exact steps; no origin-card adapter is needed.

The story has five layers. Layer 1 holds the quoted constant object poly, the
operation expr_size, the guarded scanner has_div, const_fold, and the deliberately
callable-only simplify_unsafe. Layer 2 has simplify_safe. Layer 3 composes them
as stable_simplify. Layer 4 contains the two-input generator specialize and the
public combinator @pipeline[t1,t2]. Layer 5 has specialize_zero, a generator
program fixing x0=0. Every definition uses the Library write/check/call/verify/
account/promote sequence, except simplify_unsafe: on
sub(div(x0,0),div(x0,0)), x0=0 returns Bottom(div_zero), while the rewritten
program returns Ok(0), so verification fails and promotion is forbidden.

The one-input verification family has 224 distinct programs: leaves x0 and
0..3; 100 binary trees in add/sub/mul/div-major order over those leaves; the
first 94 nested add trees formed from the first 25 binary trees and leaves;
the failure witness; 12 let saved = add(2,3) in add(tree,saved) programs over
the first 12 binary trees; and 12 cases selecting add(2,3) on is_zero(x0),
otherwise the same trees. Inputs 0..6 yield 1568 semantic comparisons per
transformer. Exact decoded layer-0 totals for const_fold are 2443 before and
1267 after (1176 saved); simplify_safe yields 1246 after. The independent
Python syntax oracle and decoded-program evaluation both check outcomes.
Call, Let and Case (case arms and default, not conditions) are recursively
transformed; Rec and Blocks remain unchanged and outside the verified family.
The safe scanner conservatively treats Case as potentially failing, including
its conditions. The separate 30-program two-input family uses 0..9, 80..89,
100..109, adding free x1; k,y in 0..6 make 1470 checked cases.

Showcase Invert searches the 105 leaf/binary programs generated from leaves
x0, 0..3 and add/sub/mul/div, with a printed literal-1 target. Exactly seven
printed programs fold to it; no indices or hash targets appear in the task.
Decide independently generates 72 programs: sub(e,e) and mul(e,0), where e
is one of x0, 0..2 or any add/div over those four leaves. The rule does not
name a witness. On x0 in 0..6, exactly 16 programs change meaning. By node
count, then compact printed text, the first witness is
Code<op (x0) = mul(div(0, 0), 0)> at x0=0: Bottom(div_zero) becomes Ok(0).
Compute retains the 224-program family and its 1568 exact comparisons.

The story records two verified outputs of specialize in a Ledger, each with produced_by
equal to (the quoted specializer hash, input code hash). Each starts callable
without evidence, receives its own bounded seven-input semantic and unfold
checks, and is promoted with its own contract. A third output created through
run_generator remains callable and separately records its produced_by tuple.
Generator evidence is never copied.

Local adapters: Library.check currently rejects polymorphic any edges; the
story filters only those mismatches during checking and restores the checker
immediately. The core has no constant-object verifier; a local verifier checks
the literal and unfold-equivalence through Library.verify. The engine adapter
is needed until the core Library can run metered atoms directly.

Requests to core: implement wildcard any in the checker; register a native
constant-object verifier; let Library.run preserve the meta engine's nested
run-budget semantics without a world-local adapter.
