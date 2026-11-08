# Geometry depth world (geometry@1)

## ASCII notation limitations

Story declarations use the core printer on written copies only when the printed
body matches the stored definition. `orientation` is the only printable tower
row; all other tower and template rows have no `decl`/`ascii`. The preserved
`design_decl` and exported body/spec remain the authoritative full implementation.
No compact fallback signatures are published.

Printer unavailable: `Ring` — ValueError: unsupported refine metadata; `twice_area`, `translate`, `Region`, `boundary_lattice`, `interior_lattice`, `isometry`, `inside`, `Signature`, `congruent`, `overlap_lattice`, `TranslationCanon`, `DihedralCanon` — ValueError: invalid ASCII identifier; `Canon` — ValueError: unsupported template metadata.

The following displayed example families cannot be parsed by context-free
`notation.parse_expr`, and therefore intentionally have no `ascii` field:
`Ring.make` (two examples), `Region.make` (two), `Signature.make` (two),
`TranslationCanon.make` (one), `DihedralCanon.make` (one): dotted constructor
calls are not expression syntax. `@translate` (two) and `@isometry` (two)
require combinator kind context. Observation examples instead use the exact
library call name and argument, which the context-free parser accepts without
the `?` sigil. The stored inputs, outcomes, steps, and traces are unchanged.

## Core integration

`List` is a given object in the declaration, so generated compose constructors
now require a `Card("List", ...)` for fields declared with sort `List`.
`RegionPair.shape` stores a tuple of `Ring` cards instead. Its holes field uses
the non-object sort `List[Ring]`, leaving the card representation and the
published examples unchanged. Geometry's compose tags use positional field
pairs. The earlier `_normalize` inline binding issue no longer reproduces on
this core.

The domain is the 33-by-33 integer lattice. A given `Point` has coordinates in
0..32, and a given `Path` has at most 24 points. `move`, `turn`, `flip`, `cross`,
and `segments_meet` are the five given geometric atoms. `then` is a given
`CombinatorSpec` whose kernel unfold is `g(f(p))`. The additional hosts are
generic point/list constructors and accessors, structural equality, bounded
list enumeration, and elementary integer arithmetic/comparison. No host
implements polygon validity, area, hole validation, Pick's theorem, shape
normalization, or overlap. The invented overlap operation searches the
intersection of the outer-ring bounding boxes within the 33-by-33 grid;
outside points cannot count.

The table lists the published example's charged steps, which include generated
object operations; catalogue position is distinct from the computed `def_layer`.
The export calls these "Card N" rather than twelve consecutive definition layers.
Card 3 uses `Ring`/point operations, not card 2; card 4 calls card 2, not
card 3; card 5 validates `Ring` and `orientation`, not card 4 alone; card 8
uses `Region` and `twice_area`, not card 7; card 9 uses point location, not
card 8; card 10 uses `isometry` and `_normalize`, not card 9; card 11 uses
card 10; card 12 uses `Region`/point location, not card 11. These are honest
DAG dependencies, not an artificial 12-link chain.

`Canon[T,group]` is a promoted definition template with two promoted refine
instances: `TranslationCanon` uses `_normalize`; `DihedralCanon` uses
`_dihedral_normalize` through `Signature.make`. The verified family contains
only `Region` under these two symmetry groups. Each member is checked on
two translated isosceles triangles and one scalene triangle; the latter
distinguishes translation-only normalization from the eight D4 actions.
Each instance has its own export row separate from the tower.
Their published scalene constructor runs cost 332 and 5432 steps respectively;
none of the twelve pre-existing tower example outcomes or step counts change.
Generated refine-object `.base` atoms and learner runs validate card shape and
canonical refinements by replaying the constructors on immutable card values;
malformed cards return `Bottom(invalid)` rather than reaching a core accessor
that could raise. The public `points` host accepts only given point paths;
the library's guarded probe handles valid invented rings and regions. The
generated `RegionPair.shape` is guarded to enforce the declared four-hole
bound and validate each ring, not just its top-level sort. Constructor example
texts name `.make` and render the actual path, pair, or region argument;
their replayed outcomes and charged steps remain unchanged.
Exported call trees retain up to 32 nodes for each primary example; elided nodes
still contribute to the exact charged step count.

| Position | Card | Kind | `def_layer` | Bounded evidence | Example steps |
| --- | --- | --- | ---: | --- | ---: |
| 1 | `Ring` | object | 1 | 50 oriented triangles | 155 |
| 2 | `twice_area` | operation | 2 | 50 oriented triangles | 22 |
| 3 | `translate` | combinator | 3 | 48 small triangles and 2 displayed triangles, all 4 shift pairs | 220 |
| 4 | `orientation` | observation | 3 | 50 oriented triangles | 24 |
| 5 | `Region` | object | 4 | 49 one-hole squares plus one two-hole region | 1862 |
| 6 | `boundary_lattice` | operation | 5 | those 50 regions | 450 |
| 7 | `interior_lattice` | observation | 6 | those 50 regions | 577 |
| 8 | `isometry` | combinator | 7 | 48 triangles and 2 displayed holed regions, two shifts and one reflection | 7339 |
| 9 | `inside` | observation | 5 | 56 region/point pairs | 356 |
| 10 | `Signature` | object | 8 | 50 translated triangles and all eight D4 actions | 8696 |
| 11 | `congruent` | operation | 9 | 50 region pairs (reference on all; full kernel inline on first) | 102115 |
| 12 | `overlap_lattice` | observation | 6 | 50 pairs on the 33-by-33 grid, bounding-box-pruned | 135524 |

The published failure is `Ring.make(Path<(0,0),(2,2),(0,2),(2,0)>)`, which returns
`Bottom(invalid)` from the kernel. Exhausting fuel produces `Unknown(fuel)`.
The three showcase answers are independently recomputed by the kernel;
inversion checks all eight D4 actions at the unique bounding-box-aligned
displacement. The full fresh-export comparison is marked slow (it takes over
60 seconds); the default suite builds the first three cards from scratch and
shares one fresh full library through a module-scoped fixture. The
standalone `geometry.py` independently checks every published depth value.

`adapter.py` supplies a public-probe observation verification hook for
region-plus-point and region-pair observations, a bounded operation verifier
that tests all 50 congruences but fully inlines one representative congruence,
and a compose-object verifier that checks the constructor on all 50 region
pairs. Each local verifier binds the digest of its exact checked domain before
promotion. Other kinds use the core verifier. The core compose verifier cannot
test all 50 constructors from the one-argument region-pair domain: its
candidate-field search requires extra field witnesses and expands their
Cartesian product. The core checker cannot infer the concrete element type
returned by generic list indexing or the generated operations of invented
objects; `GeometryLibrary.check` still runs the core definition and kind
checks, excluding those unsupported generic-list type inferences. The public
`points` probe reads the path or the publicly visible ring/region arguments;
there is no sealed state.

Refined entry and `.base` access use the world-local validated-card cache.
An uncached card is reconstructed by its kernel constructor and compared for
exact canonical equality before it can enter; cached cards have already passed
that check. This avoids repeating deep region validation at every internal
operation edge while retaining the original tower costs and rejecting forged
cards. Callable smoke tests use small triangles; bounded verification still
includes the recorded large regions.

Deviations from the depth sketch: `Signature.make` stores a canonical
origin-normalized `Region` card (rendered as its canonical point tuple),
preserving the refine-object verifier's idempotence obligation. The three
multi-argument observations take one public tuple of inputs internally.
`RegionPair` is a parameterized, invented compose object so that `Region`
can be a genuinely validated, canonical refine object. Helper operations
for D4 actions, public point location, and normalization are themselves
verified and promoted. The bounding-box-pruned 33-by-33 overlap count runs
for each of the 50 bounded region pairs; no larger scope is claimed.
`Signature` runs the full pairwise-distance-checked `isometry` on the identity
variant; the other seven D4 variants apply the same checked `Ring.make` and
`Region.make` reconstruction directly before normalization, avoiding seven
redundant all-pairs checks per signature.
