# Roads depth world (v1)

## ASCII limitations

The export preserves catalogue declarations in `design_decl`. Only printer
output that re-parses to the stored body appears as `decl` and `ascii`.

Route: printer unavailable — ValueError: invalid ASCII identifier.
cost: printer unavailable — ValueError: invalid ASCII identifier.
explore: printer unavailable — ValueError: invalid ASCII identifier.
best: printer unavailable — ValueError: invalid ASCII identifier.
optimal: printer unavailable — ValueError: invalid ASCII identifier.
Closure: printer unavailable — ValueError: invalid ASCII identifier.
close: printer unavailable — ValueError: invalid ASCII identifier.
survives: printer unavailable — ValueError: dependencies cannot be represented in their current order.
worst: printer unavailable — ValueError: invalid ASCII identifier.
mincut: printer unavailable — ValueError: invalid ASCII identifier.
cut_certificate: printer unavailable — ValueError: invalid ASCII identifier.

The following example texts cannot be parsed without a declaration context or
an expression grammar extension: `Route` (Metro), `Closure` (Metro and small
graph), `explore` (Metro and small graph), and `failures` (Metro and small graph).
The three object examples invoke generated `.make` operations, which the core
expression parser only treats as card-tag syntax. The four combinator examples
contain operation-reference slots and a `?size{...}` wrapper; parsing those
sigils requires the library context, whereas the shared export finalizer calls
`parse_expr` without one. Their evaluated values, steps, and traces are unchanged.

## Layer zero

`Metro` is a fully public, canonical, undirected graph of 12 vertices and 23
positive-weight edges. `Roads` accepts sorted, distinct vertex names (2..20)
and sorted distinct weighted edge triples. `Edge` is explicitly declared. Given
`Edges`, `Worst`, `Bottom`, `List`, integer, text, and boolean values have
counted generic constructors, accessors, equality, arithmetic, and finite-list
operations. `edge` returns one public road weight or `Bottom(no_edge)`;
`map_view` exposes *all* active roads, including a constructed `Closure` by
calling the generated `Closure` accessors and folding public edges in the
kernel. The host probe rejects closures; only the kernel's checked object
constructor mints accepted closures. `Route` accessors likewise accept only
cards minted through `Route.make`. An equivalent generic card is rejected
at the object boundary until reconstructed through the checked constructor;
`size` reads only a visible finite list. Generic `sort_frontier`,
`sort_edge_sets`, and `sort_texts` sort lists; they do not search routes,
generate failures, derive cuts, or change the graph. The generated object
pipeline supplies `Route.make`, `Route.graph`, `Route.vertices`, `Closure.make`,
`Closure.base`, and `Closure.closed_edges`. These generated operations form the
sealed object interfaces; later tower cards use them without appearing in the
interfaces. `@chain` and the core `@fix` have public kernel
unfold rules; the latter is actually used to compute reachability closures
with a decreasing finite-height counter. Core `Rec` with a list-size measure
performs route validation, subset enumeration, edge folds, and partition cuts;
the DFS and frontier worklists use the explicitly fuel-bounded recursion mode.

## Tower and bounded evidence

Each row is an invented, checked, callable, verified, accounted, **promoted**
definition. Every card checks all 256 weightings (each road weight 1..4) of one
fixed connected four-vertex/four-road graph (A-B, A-C, B-D, C-D): complete for
that topology and weight bound, no other topology is claimed. Each combinator
checks **both** operation-slot implementations over those 256 graphs (512
executions). Review RB7: earlier rounds used only the first 60 weightings
(AB = 1 in all of them). Each row lists the
*current charged steps of its first Metro example*, not wall time. The export's
`cost.example_steps` records current charged steps for each shown run. The
catalogue layer is the row number, while the actual dependency layer is shown
separately; no layers are artificially padded.

| Catalogue | Kind | Name | Dependency layer | Metro steps | Invention |
| --- | --- | --- | ---: | ---: | --- |
| 1 | object | `Route` | 1 | 44 | Refine a real parameterized `(graph,vertices)` record after public edge and distinctness checks. |
| 2 | operation | `cost` | 2 | 871 | Sum each checked segment's public weight. |
| 3 | combinator | `@explore` | 2 | 92,732 | Enumerate all 419 Metro A-L simple routes, in vertex order. |
| 4 | operation | `best` | 3 | 2,517 | Cheapest route with lexicographic tie breaking. |
| 5 | observation | `?optimal` | 4 | 4,663 | Compare the public route cost against `best` on the granted map. |
| 6 | object | `Closure` | 2 | 129 | Refine `(base,closed)`; canonicalize and verify the edge-ID subset. |
| 7 | operation | `close` | 3 | 260 | Make the checked closure; `edge`/`map_view` expose its active roads. |
| 8 | combinator | `@failures` | 1 | 88,850 | Enumerate subsets in size-then-lex order, applying each closure slot. |
| 9 | observation | `?survives` | 4 | 414,999 | Require every allowed closure's public reachability fixed point to contain the target. |
| 10 | operation | `worst` | 4 | 47,054,810 | Build the actual `Worst(cost,Edges,Route)` record with both tie rules. |
| 11 | operation | `mincut` | 2 | 314,487 | Enumerate 1,024 endpoint partitions and compare derived `boundary(g,X)` edge sets. |
| 12 | observation | `?cut_certificate` | 5 | 730,669 | Check all smaller failures still survive, then check the exhibited cut disconnects. |

The independent `worlds/catalogue/depth/roads.py` is imported in the tests and
the bounded verification references; the exported Metro answers are also
asserted against the original twelve catalogue values. Each example is
evaluated by the kernel. The two large list-producing examples evaluate the
*stated* expression `?size{@explore[...]...}` / `?size{@failures[...]...}`
instead of serializing 419 duplicated graph-valued routes or 277 duplicated
graph-valued closures. Those counts are 419 and 277. Trace trees for large
runs explicitly mark elision, while outcomes, steps and input values remain
exact. All examples now use actual kernel tracing and `trace_json` (with a
temporarily raised recursion limit for the serializer's subtree counts),
including the full large worst/certificate runs. The public export is under
12 MB. The exported failure is
`best(Metro,A,Z) -> Bottom(no_route)`, and a
finite `fuel` limit on a Metro search produces `Unknown(fuel)` without
presenting an incomplete search as a proof.

## Design deviations and review fixes

- `best` uses a counted positive-weight frontier search with settled junctions
  rather than materializing *every* `@explore` route before minimization. It
  still calls the lower `Route.make` and `cost` cards, gives the exact same
  shortest route and tie rule, and makes 277 worst-case failures tractable.
- `best` preserves the original checked closure in its route while searching
  over the counted active map. Public calls require a route/closure minted by
  this library; deserialized cards must be reconstructed via `.make`.
  Internal graph operations validate closure fields through the core-generated
  `.base` definition. Public provenance uses a weak identity registry because
  the core generic-card primitive has no built-in provenance seal; core
  verification deep-copies its inputs, so provenance is checked at the public
  entry point rather than on those internal copies.
- Connectivity inside `?survives` and `?cut_certificate` uses the core `@fix`
  over public reachability, not a materialized list of all simple
  routes. This is equivalent for the bounded full-information graph and avoids
  multiplying 419 paths by 277 closures.
- Route and closure examples use `List<Text>` and `Edges<List<Text>>` typed
  fields, rather than the design's abbreviated flat identifiers. The public
  `Edge` sort and the derived `boundary(g,X)` helper are declared; `worst`
  explicitly constructs the promised record. Ladder ranges are disjoint:
  one route, all routes, one or two failures on 12 vertices, 13..16 vertices
  / two or three failures, then
  17..20 vertices / three failures. The first two showcases select **one**
  lexicographically first witness, not all witnesses; the third selects one
  canonical cut and its boolean certificate. Each showcase's actual kernel
  check is recorded as `answer_checked` and `check_method`.

The exported `def_layer` tracks actual dependencies, not row positions. Cards
3 (`explore`) and 8 (`failures`) do not call cards 2 (`cost`) and 7 (`close`):
card 3 calls `Route.make`, while card 8 calls its closure operation slot.
Card 4 (`best`) calls `cost` and `Route.make`, not card 3 (`explore`).
Card 6 (`Closure`) uses `road_ids`, not card 5 (`optimal`). Card 11 (`mincut`)
uses `boundary` and public edges, not card 10 (`worst`). Card 10 (`worst`)
calls `best`, `cost`, and `failures`, not card 9 (`survives`). Card 9 uses card
8's `failures` and `close`, while card 12 (`cut_certificate`) uses card 11's
`mincut` and `survives`.

## Adapters, limits, validation

`RoadsLibrary.check` resolves core-generated object operations for the
generic checker. Its observation adapter supplies the parameter names of
multi-input, public-map observations and checks the independent reference,
immutability, and equality under identical fully public maps. The core
observation implementation assumes one truth-state parameter and zero-arity
probes, so it cannot directly verify these public graph-argument operations;
the adapter retains the same write/check/callable/verify/account/promote
status transitions and hashed evidence including the exact checked-domain
digest. The declaration validator only
supports one probe truth sort, so `size` is explicitly limited to already
visible lists. The `RoadsLibrary.get` bridge gives generated object accessors
stable content hashes without turning object values into callable functions.

The complete fresh traced export takes more than 60 seconds and its equality
test runs with `OPULSE_RUN_SLOW=1`. Default tests still construct the library
fresh and rebuild the first three cards from the kernel. The test directory
runs its bounded four-vertex
families and checks every catalogue Metro value, failure behavior, I1-I4,
declaration round-trip, byte-for-byte export equality, ASCII strings and
showcase answers. Full 16..20-node enumeration is intentionally *not* claimed
as evidence: callers must publish their graph size, budget and explicit fuel
cap, and treat an exhausted run as `Unknown`, not a result. There are no
hidden roads; `learner_view` and `judge_view` are unnecessary because the
public map equals the complete truth.
