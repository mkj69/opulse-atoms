# Combinators-only conflict scheduling

`comb_only` opens only `combinator`. Fixed `Plan` and `State` values encode finite
conflict graphs (up to 12 blocks of 16 jobs). Given operations compute local
weights and neighbors, update immutable search states, and expose public
structure; none computes an optimum. Eight promoted kernel definitions build
measured map, fold, iteration, closure, divide, components, branching, and
exact branch-and-bound search. `@opt` splits disconnected components, uses
the positive-weight `@map`/`@fold` bound, and preserves lexicographic ties.

The checked-in design is `worlds/catalogue/depth/comb_only.json` and the locked
declaration is `worlds/decl/v2/comb_only@1.json`. Regenerate with
`PYTHONPATH=src python3 -m opulse.worlds_v2.comb_only.export` and run
`PYTHONPATH=src python3 -m pytest tests/worlds_v2/comb_only`.
