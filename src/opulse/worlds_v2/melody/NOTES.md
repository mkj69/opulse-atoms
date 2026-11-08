# Melody depth world

Motif: printer unavailable — unsupported refine metadata.
occurs: printer unavailable — dependencies cannot be represented in their current order.
scan: printer unavailable — dependencies cannot be represented in their current order.
realize: printer unavailable — dependencies cannot be represented in their current order.
motif_at: printer unavailable — dependencies cannot be represented in their current order.
Score: printer unavailable — unsupported refine metadata.
count_covers: printer unavailable — dependencies cannot be represented in their current order.
cover_count: printer unavailable — dependencies cannot be represented in their current order.
best_cover: printer unavailable — dependencies cannot be represented in their current order.
perform: printer unavailable — dependencies cannot be represented in their current order.
cover_report: printer unavailable — dependencies cannot be represented in their current order.

The public state is a 1..64-note melody with pitches 48..84 and durations 1..4. The
given atoms are `note_shift`, `transpose`, `slice_events`, `concat`, the granted exact
`events` and `beats` probes, a `score_view` probe for public scores, and elementary
finite-list and integer operations. The registered given combinator `map_notes`
applies an indexed typed operation and seals the melody. Every operation is counted
by the kernel. `transpose` costs one step per source event and `slice_events`
one per copied event on valid calls; invalid calls cost one step. `concat` and
the probes cost one step per call. The declaration records both argument-based
cost rules; its integer cost is the one-step fallback for invalid calls.

| Design layer | Kind | Definition | Method and scope | Example steps |
|---|---|---|---|---:|
| 1 | object | Motif: parameterized refined offset/duration list | bounded 56 motif lists | 55 |
| 2 | operation | occurs: aligned relative pitch and exact duration | bounded 192 source/motif/start triples | 662 |
| 3 | combinator | scan: all legal starts, including overlaps | bounded 64 cases x 2 operation slots | 15603 |
| 4 | observation | intervals: adjacent pitch changes and departing durations | bounded 64 melodies | 59 |
| 5 | operation | realize: root-relative melody with range checks | bounded 63 motif/root pairs | 1547 |
| 6 | operation | motif_at: extract and normalize a slice | bounded 64 slices | 283 |
| 7 | object | Score: parameterized ordered distinct-motif library | bounded 64 melody/library pairs | 762 |
| 8 | combinator | count_covers: scan-match suffix recurrence | bounded 64 cases x 2 operation slots | 355653 |
| 9 | observation | cover_count: exact public count | bounded 64 scores | 355653 |
| 10 | operation | best_cover: fewest tiles, then lexicographic plan | bounded 64 scores | 1018214 |
| 11 | combinator | perform: exact reconstruct-and-check | bounded 64 cases x 2 operation slots | 21822 |
| 12 | observation | cover_report: count, plan, exact beats | bounded 64 scores | 2413908 |

These are genuine listed-input families, not claims about the whole 64-note domain.
Card `cost.steps` ranges are over those verification families; `example_steps`
ranges are over the shown examples, including the 36-note showcase score. The
`perform` example also includes a kernel-produced `Bottom(mismatch)` failure. Both
count and optimal-plan recurrences use measured memo-enabled `Rec`; memo work is
recorded separately from the charged plain recursion by the core. No additional
world-specific fixpoint, turns, or derived structural fold is needed.

Design-layer numbers and computed dependency layers differ: the latter never get
padded to the displayed tower position. In particular, independent interval
extraction remains dependency layer 1. The reference's `realize` pseudocode uses a
closure inside `map_notes`; kernel operation slots do not capture a runtime root,
so `realize` unfolds an equivalent indexed recursion and seals with `Melody.make`.
The primary depth examples intentionally reuse the 36-note score at layers
7..12 because the independent design fixes those exact outputs.
`count_covers` precomputes each `scan` once, preserving the finite DAG recurrence.
Card 4 uses `events`, not card 3; card 5 uses `Motif.base`, not card 4;
card 6 uses `slice_events` and `Motif.make`, not card 5; card 7 validates
`events` and `Motif.make`, not card 6. Card 10 runs an independent optimal-plan
recurrence, not card 9; card 11 checks supplied plans using `realize`, not card
10; card 12 composes `cover_count`, `best_cover` and `beats`, not card 11.
Each exported card also supplies a smaller fresh-input kernel example; layers
8..12 use distinct short scores with different roots. Generated `Motif.make`
and `Score.make` use the core's generic `Bottom(invalid)` for invalid literals
instead of the reference's more specific motif/library reasons.

The world publishes no sealed truth: scores and melodies are public values.
The full twelve-card fresh build and 36-note showcase take more than a minute
on the current core; the default tests freshly verify the first three cards
and their random small scans. Set `OPULSE_RUN_SLOW=1` for the full tower,
showcase and committed-export equality tests.
`adapter.py` is necessary because the core observation checker only permits
observations to call other observations and given operations: the two derived
public observations also call invented combinators and operations. The adapter
obtains only granted probes, then checks reference equality, immutable public
facts, and indistinguishability on each bounded batch. Generic tuple-valued
operations also need the world's checker to defer dynamic `unknown` sort checks
to the runtime. Replace the local observation adapter with the core combinator-
aware checker when available.
The extra `score_view` granted probe exposes the public `Score` object to the
core observation API, which otherwise accepts only probe values as inputs.
Hosts and learner runs reject malformed or invented-sort cards, including nested
invalid motifs and malformed scores, by checking complete shapes and refinements.
The local `_stored` guards remain necessary: the core accessor treats the
tuple-backed given `List` base as requiring a `List` card, so even a valid
`Motif<((0,1),(-3,1))>` is rejected before its `valid` expression can run;
`occurs` then produces `Bottom(nan_condition)` instead of the reference's
boolean result. The guards also reject forged, invalid nested motifs.
The checker permits only the explicitly listed static Nat/int and sentinel
compatibility diagnostics in the existing tower; unrelated argument mismatches
remain errors. Observation evidence checks dependencies, reference results,
unchanged encoded public states, and non-interference within eight-state batches.

The slow-marked full-build tests verify bounded families, compare all twelve
independent depth fixtures, and compare the fresh export with the committed
artifact. Default tests exercise the first three cards, invalid constructors,
argument-based costs, and random transposition boundaries. No local generic
probe, object-verifier or given-combinator scope replacement is introduced.

ASCII notation limitation (core parser): `parse_expr` without a context rejects
the `@scan`, `@count_covers`, `@perform`, `?intervals`, `?cover_count`, and
`?cover_report` examples even though those expressions parse with the world's
kind/arity context and preserve the evaluated arguments. The four `Motif.make`
and `Score.make` examples retain the exact evaluated constructor call:
`parse_expr("Motif.make(List<...>)")` cannot parse a generated `.make` call.
These examples therefore have no `ascii` field in the shared finalizer; their
`text` remains the exact call. The compact definition printer cannot emit
these stored definitions; the export does not substitute generated-call aliases
for their bodies. Their verified execution is unchanged.
