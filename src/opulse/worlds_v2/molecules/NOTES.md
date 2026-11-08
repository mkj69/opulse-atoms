# Molecules v1: depth world

This is an exact, finite **single-bond valence graph** world, not a model of chemical stability, energy, reactions, or stereochemistry. A given `Graph` has one to eight numbered C/O heavy atoms, sorted unique simple heavy-heavy edges, and one attached-H count per heavy atom. There are at most 32 total atoms. C has valence four; O has valence two. Intermediate graphs may be unsaturated or disconnected. The given atoms are `attach`, `link`, `identity`, and the granted probes `atoms`, `count`, and `group_sizes`. Additional layer-zero atoms construct and access graph cards and finite lists, compare finite values, and perform small-integer arithmetic; `graph_valid` checks the given `Graph` sort. `list_label_permutations` is a generic bounded list-permutation primitive: it groups indices with equal pairs of values, rather than implementing graph isomorphism in a host. Connectivity, graph relabeling, canonical minimum selection, saturation, skeleton enumeration, feature extraction, grouping, and ambiguity selection all run as kernel nodes.

## Tower and finite verification

These are the **published design layers**. `def_layer` counts real dependencies; it deliberately does not pad the tower to twelve dependency levels. Steps are the measured layer-zero steps of the first published example, not compressed steps. The design's count/size values for layers 6, 8, and 11 are preserved as `design_value` while the displayed example executes the named card.

| Design layer | Kind | Invented card | `def_layer` | Verification method and exact scope size | Example steps |
| --- | --- | --- | ---: | --- | ---: |
| 1 | object | `Molecule`: connected, canonicalized graph refinement | 3 | bounded, 65 graphs with at most 3 heavy atoms | 28 |
| 2 | operation | `saturate`: fill each remaining valence with H | 4 | bounded, 65 connected graphs with at most 3 heavy atoms | 76 |
| 3 | combinator | `finish`: transform, then saturate | 5 | bounded, 55 graphs, two graph-operation slots | 254 |
| 4 | observation | `formula`: granted atoms probe counts | 4 | bounded, 55 connected molecules | 199 |
| 5 | observation | `cycle_rank`: edges minus heavy vertices plus one | 4 | bounded, 55 connected molecules | 35 |
| 6 | operation | `candidates`: enumerate graph edge subsets and canonical isomers | 6 | bounded, 54 (C,O,edge-budget) triples, 2–4 heavy vertices and invalid budgets | 12,926 for direct four-heavy example; C5H12O enumeration is checked separately |
| 7 | observation | `oh_count`: C-O-H detection | 4 | bounded, 55 connected molecules | 97 |
| 8 | combinator | `screen`: filter with a parameterized probe | 1 | bounded, 54 prefixes/targets, two observation slots | 429 |
| 9 | object | `Profile`: genuine four-field core compose object | 1 | bounded, 50 different four-field profiles | 1 |
| 10 | operation | `profile`: reuse three observations and count heavy C branches | 5 | bounded, 55 connected molecules | 636 |
| 11 | combinator | `partition`: group codes by parameterized probe | 4 | bounded, 50 input lists, two probe slots | 1,979 |
| 12 | observation | `ambiguity`: largest class with minimal-profile tie-break | 2 | bounded, 50 single-group inputs with real canonical graph codes and their computed profiles | 132 |

The helper cards `connected`, `relabel`, `normalize`, `all_pairs`, and `carbon_branches` also go through write/check/callable/verify/account/promote. `all_pairs` is exhaustive on its **whole supported domain** of nine sizes, 0–8. Other checks are bounded: they do **not** assert exhaustive verification of all graphs up to eight heavy atoms. Observations are compared with the independent depth reference on all recorded inputs; operations and combinators check both their reference and kernel unfolding. `Molecule` uses the core object verifier, including canon totality, idempotence, and validity preservation; `Profile` uses the core object constructor. The 14 isomers of C5H12O and the three showcase answers are recomputed by the kernel and cross-checked against `worlds/catalogue/depth/molecules.py`. A failed `saturate(Graph<C,C>)` is exported as `Bottom(invalid)` (57 steps). The export is under 3 MB. Every published example has a real `trace_json` trace; the large enumeration is independently rechecked during export rather than duplicated as an untraced example.

## Deliberate deviations and adapters

- Five examples retain their evaluated calls as `text` without `ascii`: the `Molecule.make(Graph.val<...>)` and `Profile.profile(...)` object constructors (dotted calls are not in the expression grammar), and the `@finish[...]`, `@screen[...]`, and `@partition[...]` combinators (the context-free `parse_expr` used by `finalize_export` cannot resolve the `@` sigil or encode a `FnRef` as a standalone argument; `@screen` additionally passes an observation as a slot, which the parser's operation-only slot grammar rejects). All other example texts use literal structural values (including graph labels, bonds, hydrogen counts, and list/map entries) and parse as their evaluated calls. Observations use ordinary call syntax for the same evaluated `Call` node because context-free `parse_expr` cannot resolve `?` either.
- The export publishes ASCII only when the compact printer's output parses to the stored body. Unprintable rows retain their design text and verified body without substitute source.
Molecule: printer unavailable — dependencies cannot be represented in their current order.
saturate: printer unavailable — invalid ASCII identifier.
formula: printer unavailable — invalid ASCII identifier.
cycle_rank: printer unavailable — invalid ASCII identifier.
candidates: printer unavailable — invalid ASCII identifier.
oh_count: printer unavailable — invalid ASCII identifier.
Profile: printer unavailable — printed definition does not re-parse to stored body.
profile: printer unavailable — invalid ASCII identifier.
partition: printer unavailable — invalid ASCII identifier.
ambiguity: printer unavailable — invalid ASCII identifier.

- `@chain` currently has two operation slots (`first`, `second`) with a public core-node unfold, rather than a runtime list of `FnRef` values. The kernel cannot invoke an operation reference stored inside a list; two-slot composition propagates failures identically. Extending its arity to a list is pending a kernel facility for dynamic operation-list invocation.
- The four-count `Profile` is constructed by the core compose-object operations, not by a named constant. The `Molecule` refine constructor is `Molecule.make(graph)`; its canonicalization is computed by invented `normalize` after the connectedness test.
- The catalogue's layer 6/8/11 count and group-size results remain exact `design_value` fields, checked against the recomputed kernel results, while each first example calls `candidates`, `screen`, or `partition` directly. Their outputs are lists/maps, not the catalogue's derived counts. Layer 12 takes a pre-grouped map as its declared input; its body reconstructs each group key using the invented `Profile` constructor and fields before ranking, yielding an honest `def_layer` of 2 and rejecting malformed keys. It cannot call the preceding `partition` card without changing its declared group-map interface. The catalogue's layer-12 witness and answer are unchanged.
- The `MoleculeLibrary` observation bridge remains necessary because the core observation checker requires probes to take the subject directly; here the probe reads the graph extracted from a molecule, or an explicit public group map. Local evidence binds its exact checked-domain digest. Core verifiers handle objects (including `Profile`'s `finite_values`), operations, and combinators. `Profile` checks 50 distinct sample cards and one explicit primitive constructor tuple. Replace the observation bridge with a world-parametric core checker when available.
- `list_label_permutations`, `list_permute`, and `list_reindex_pairs` are **generic bounded list primitives**, not hosts for graph isomorphism: invented `relabel` constructs each permuted graph, and invented `normalize` selects the minimum by measured, balanced kernel recursion. Its recursion depth is logarithmic even for an eight-heavy-atom graph, though enumerating a fully symmetric eight-atom graph still takes substantial time. `list_combinations` enumerates finite subsets; the kernel checks validity and connectivity and independently canonicalizes their results. `graph_key` merely serializes a numbered graph and cannot compute a canonical graph by itself.
- No fixpoint, memoized recursion, interleaving, or derived structural fold is needed by these twelve cards; their measured `Rec` nodes already express the required finite graph/list recursions. No world-specific replacement for a spec-0.3 combinator is introduced.

The test suite intentionally keeps six-heavy skeleton enumeration in **one** export fixture to stay below 120 seconds. A separate full 6-heavy parameter sweep is not in the normal suite; add it under `@pytest.mark.slow` if extending evidence beyond these bounds.
