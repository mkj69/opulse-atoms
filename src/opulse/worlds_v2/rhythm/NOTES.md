# Rhythm depth: phase inference on discrete ternary cycles

## ASCII notation limits

The original design declarations remain in `design_decl`. Only five story rows
have `decl` and `ascii` that re-parse to the stored body; unsupported bodies
publish neither. The compact grammar only names objects with uppercase initials,
only supports record-based refinements with an optional named canonicalizer,
and cannot spell generated `accented.make` / `cycle.make` constructor calls.
The stored definition and recorded evaluation remain authoritative.

The following examples cannot be parsed by standalone `notation.parse_expr`
while retaining the expression actually evaluated (but can be read with the
appropriate world/kind context, except `.make`): both examples of `accented`
and `cycle` use generated `.make` calls; both examples of `stack`, `weave`, and
`orbit` use combinator sigils. Observation examples use the underlying plain
call spelling, which parses standalone and evaluates the same observation.
All operation examples, including the `start_heavy` failure, are standalone
parseable expressions.

## Core issues

`kernel.inline` renames a call to an atom when a definition parameter shares
the atom's name, even though direct evaluation calls the atom. Minimal repro:

```python
from opulse.atoms import kernel as k, nodes as n
scope = k.DictScope([k.Atom('first', 1, lambda pair: pair[0])],
                    [k.Defn('f', ('first',), n.Call('first', (n.Lit((1, 2)),)))])
expr = n.Call('f', (n.Lit(7),))
assert k.evaluate(expr, scope=scope).outcome == k.Ok(1)
k.evaluate(k.inline(expr, scope), scope=scope)  # KeyError: '__inline_arg_1'
```

Rhythm avoids the collision by naming its local voice bindings `voice_a` and
`voice_b`, keeping the public `first` and `second` atoms unchanged.

Layer 0: `Rhythm` contains 1-512 origin-preserving cells in {0,1,2}; `left` rotates
modulo the actual length (negative offsets work), `identity` preserves its input,
`@seq` unfolds as `g(f(x))`, and `?cells` publishes every cell (or both public
cycle values when given a pair of cycles). The remaining
given hosts are only constructors, accessors, list primitives, structural
equality, and bounded integer arithmetic. The base host validates only ternary
cells; `Accented.make` checks heavy cells, and `Cycle.make` finds the shortest
period in its invented definition, not in a host. The public pair of cycles is fully
visible for `best_fit` and `phase_count`; there is no sealed hidden truth.

| Tower | Kind | Invention | Evidence scope | Design-example layer-0 steps |
|---|---|---|---|---:|
| 1 | object | Accented, nonempty heavy subset | bounded, 110 words <=4 cells | 9 |
| 2 | operation | first heavy to zero | bounded, 81 accented words <=4 cells | 17 |
| 3 | combinator | same-input pointwise max | bounded, 54 accented words <=4 cells; identity/start_heavy slots | 219 |
| 4 | observation | odd-index heavy count | bounded, 81 words <=4 cells | 105 |
| 5 | object | origin-preserving shortest whole period | bounded, 81 words <=4 cells | 126 |
| 6 | operation | full-LCM Hamming and offbeat | bounded, 135 pair/shift tuples <=2 cells | 2346 |
| 7 | combinator | full-LCM weave of two transformed voices | bounded, 64 heavy-cycle pairs <=4 cells; identity/start_heavy slots | 1251 |
| 8 | observation | lexicographic best rotation | bounded, 54 cycle pairs <=2 cells | 79902 |
| 9 | operation | suppress nonheavy cells | bounded, 54 cycles <=4 cells | 218 |
| 10 | combinator | first-seen distinct transformed rotations | bounded, 54 cycles <=4 cells; identity/silence_weak slots | 2692 |
| 11 | observation | all minimum-error distinct rotations | bounded, 54 cycle pairs <=2 cells | 117674 |
| 12 | operation | inverse two-voice phase search | bounded, 54 observed/voice triples <=2 cells | 697544 |

Every design example is checked against the standalone stdlib implementation
`worlds/catalogue/depth/rhythm.py`. The exported second example of every card
uses fresh material, checks its kernel outcome against the reference, and
passes lower-layer products as inputs wherever needed. The 1/2-cell phase-score
domain is also independently checked exhaustively across all valid shifts. The `start_heavy` card
exports `Bottom(no_accent)` on an accent-free rhythm;
the generated refinement constructor returns `Bottom(invalid)`. Evidence scopes above are
the actual finite checked families, **not** claims about all 512-cell rhythms
or every pair of phase slots. The two 12/16-cell showcase searches (gcd 4,
not coprime) are
computed through the same kernel. A 15/16-cell example checks 240-cell LCM.

Adapters: invented objects now use core-generated `.make` / `.base` operations,
core `check_object` / `verify_object`, and `Card(sort, "val", (base,))` wrappers.
The `left` host preserves valid `Accented` and `Cycle` wrappers, and rejects
malformed or noncanonical input cards without minting invented refinements.
The redundant `make_accented` and `make_cycle` hosts were removed.
`RhythmLibrary.check` delegates to `check_definition` and checks the core's
combinator rule; it ignores only generic `any` / tuple `list` sort edge errors,
which the current declaration checker cannot polymorphically type. The
The core checks, calls, and verifies `offbeat` directly. `adapter.py` remains
for `best_fit` and `phase_count`, whose bodies call invented operations that
the core's observation checker forbids; it checks direct-run/inline step parity
and probe non-interference on their exact recorded domains. Every local
evidence record carries the core's checked-domain digest. The observation
bodies declare `arg0` as the subject instead of the default `s`.
No extra combination mode from spec 0.3 is needed: the three invented
combinators use measured `Rec` and public `Call` unfold rules.

Deviations: computed `def_layer` differs from design tower presentation layers
when the design only supplies an operation in a slot rather than calling it in
the stored body. Card 3 uses supplied slots, not card 2 by name; card 4 uses
`cells`, not card 3; card 5 uses `cells`, not card 4; card 7 uses `cycle.make`,
not card 6; card 9 uses `cycle.make`, not card 8; card 10 uses `cycle.make` and
its operation slot, not card 9 by name; card 12 uses `weave`, `phase_score`,
and `offbeat`, not card 11. `phase_score` calls the lower `offbeat` observation explicitly;
objects call generated core constructors, not their own names. The declared
object names are lowercase for static sort compatibility,
while their design presentation is `Accented` / `Cycle`. The declaration adds
minimal generic `any` and `list` sorts for validation. The `phase_score` body
materializes an overlay for `offbeat` after tallying cell mismatches; both
statistics are computed over the complete least-common-multiple window.
No slow-marked test is required; the rhythm
test directory stays below 120 seconds.
## Published source: printer unavailable

- accented: printer unavailable — ValueError: invalid declaration name.
- start_heavy: printer unavailable — ValueError: invalid ASCII identifier.
- cycle: printer unavailable — ValueError: invalid declaration name.
- phase_score: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
- weave: printer unavailable — ValueError: invalid ASCII identifier.
- silence_weak: printer unavailable — ValueError: invalid ASCII identifier.
- infer_phase: printer unavailable — ValueError: operation metadata has no compact ASCII declaration.
