# op_only

Finite directed relations with only `operation` open for learner inventions.
The locked declaration lives in `worlds/decl/v2/op_only@1.json`; layer-zero
hosts and fixed combinators supply public relation operations and probes.
`fix2` and `dag_fold` invoke their plugged operations through the metered kernel;
`advance` is built from profile field reads, comparison, addition, and `set_profile`.
`story.build_library()` writes, checks, makes callable, verifies on an explicit
finite braid, accounts for, and promotes all nine story operations and their
`critical_edge` helper. `algorithms.py` supplies generic bitset relation operators;
the separate binding
`reference.py` checks the design examples and showcase certificates.

Regenerate the declaration before the replayable export with
`PYTHONPATH=src python -m opulse.worlds_v2.op_only.decl_source`, then
`PYTHONPATH=src python -m opulse.worlds_v2.op_only.export` and
`PYTHONPATH=src python -m opulse.worlds_v2.index`.
