# comb_obs

The warehouse is a closed 64x64 terrain: `scan` reveals a 7x7 patch, and
`move`, `charge`, `pick`, and `deliver` are the only physical actions. Fixed
generic graph, list and arithmetic primitives inspect only their explicit
inputs. Search, frontier selection, exploration, scheduling, cargo execution
and audit folds unfold through kernel recursion. The
declaration opens only combinators and observations. Eight inventions pass
through the core written, checked, callable, verified, and promoted pipeline.

Run `PYTHONPATH=src python -m opulse.worlds_v2.comb_obs.declgen` to regenerate
the layer-zero declaration and its host lock, then
`PYTHONPATH=src python -m opulse.worlds_v2.comb_obs.export` to regenerate
`docs/assets/data/worlds_v2/comb_obs.json`; run
`PYTHONPATH=src pytest tests/worlds_v2/comb_obs` to check the binding examples.
The design lives in `worlds/catalogue/depth/comb_obs.json`; `reference.py` is the independent oracle.
