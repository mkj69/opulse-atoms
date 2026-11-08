# Cross-world multiplication transfer

This experiment tests whether the **preloaded** saved integer `mul` can be
reused for the 16 frozen `machine_stage2.json` dot tasks via two verified,
partial bridges. G1 has no integer library; G2 has a pre-scripted saved
operation in integer world B; G3 has given `mul` in integer world A. The
scripted stage-1 state is created before each stage-2 episode, not measured
as a separate task block. See [PREREG.md](PREREG.md) for the decision rule
and [INTERFACE.md](INTERFACE.md) for MASM's one new instruction.
The primary outcome is the G2/G1 ratio of median episode totals of MASM
length written in-task, including local helpers; accuracy is a secondary
non-inferiority check. The 2026-11-05 preregistration amendment predates all
real runs. Offline scripted runs are diagnostics, not evidence of transfer.

At the repository root, set `PYTHONPATH=src:experiments/atoms_bridge:experiments/atoms_mul`.
Reproduce offline runs (scripted diagnostics, **not** learner evidence):

```sh
python -m atoms_bridge.run --policy transfer --groups A,B,C --episodes 2 --run-id dryrun_transfer --out experiments/atoms_bridge/runs
python -m atoms_bridge.run --policy unroll --groups A,B,C --episodes 1 --run-id dryrun_unroll --out experiments/atoms_bridge/runs
python -m atoms_bridge.summary --run experiments/atoms_bridge/runs/dryrun_transfer
python -m atoms_mul.analysis.cost --prompts experiments/atoms_bridge/runs/dryrun_transfer/prompts.jsonl --episodes 40
```

The shared harness writes `config.json`, `prompts.jsonl`, `results.jsonl`
and `summary.json`. `--resume` validates run configuration and skips completed
episodes. Use a fresh run ID after changing bridge source or frozen tasks.
The shared cost estimator projects 2,880 expected / 5,760 worst-case API
calls at 40 episodes, with roughly 806,940 / 1,613,880 input tokens and
864,000 / 5,898,240 output tokens. Dollar costs require a supervisor-approved
model and pricing; no API call is made during these diagnostics.
Group labels A/B/C in the shared runner correspond to G1/G2/G3. The fixed
saved source costs 13 AML size units per G2 episode; MASM line counts are
reported separately, not added to AML units. The recorded
verification scope of saved `mul` is 0..255 x 0..20; out-of-scope G2 calls
return `Bottom(outside_domain)` instead of executing an unverified body.
Bridge-to-byte admits 0..255; modulo reduction is an explicit separate call.
The bridge accepts refined `nat` cards, unwraps them through `nat.base` for
byte-domain checks and mapping, and constructs a checked `nat` card after
modulo reduction at the runtime boundary. Integer `mul` still receives its
original integer arguments; constructor and accessor work remains charged to
the cross-world step count.
Bridge verification uses the integer and complete computer declarations, with
the byte validity host adapted to an equivalent counted kernel atom and an
extra verification-only `byte_add` witness. Task execution uses the actual
host-State computer scope; the bridge does not claim to verify the full
machine-state interface.

The real run **requires supervisor approval; do not run**:

```sh
python -m atoms_bridge.run --policy llm --allow-api --model MODEL_APPROVED_BY_SUPERVISOR --groups A,B,C --episodes 40 --run-id real --out experiments/atoms_bridge/runs
```
