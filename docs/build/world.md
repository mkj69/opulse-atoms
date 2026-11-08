# Build / World contract

<link rel="stylesheet" href="../../assets/css/atoms2-research.css">
<script defer src="../../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

<p class="ar-kicker">BUILD / 02 &nbsp; WORLD CONTRACT</p>

## Give a finite world a contract

A world begins with typed layer-0 objects, operations, combinators, and observations. Its declaration also fixes which kinds may be invented, canonicalization rules, per-agent visibility, full-state judging, fuel, generator moves, and the evidence required for promotion. In ASCII machine notation, the Python core parses law (`#law`) and bridge (`~bridge`) definitions and checks scoped rewrites and interface commutation. The proposed SQL-style contract on this page does not run browser law or bridge checks. See [the semantics](../reference/index.md) for the v2 grammar.

<div class="ar-callout" markdown="1">
<span class="ar-badge ar-badge-design">Designed example</span>

The proposed SQL-style contract below has no database-backed evaluator or public builder CLI. Start with the [executable core-only quickstart](index.md) instead. The `circuits@1` declaration is a separate source example.
</div>

### A transaction, seen from two sides

<div class="ar-grid ar-grid-two" markdown="1">
<section class="ar-card" markdown="1">
<p class="ar-number">LEARNER / ALLOWED</p>

<span class="ar-badge ar-badge-design">Designed example</span>

**State:** a finite, typed table with at most four rows and a transaction log. **Actions:** insert a row, update a key, commit or roll back a transaction. **Observations:** a rows probe reveals only rows permitted to the acting user; a last-error probe reveals a documented error class. The learner may define a retry combinator for updates only if the world's open kinds and allowed nodes permit it.

These names are a proposed interface, not installed primitives.
</section>
<section class="ar-card" markdown="1">
<p class="ar-number">JUDGE / REQUIRED</p>

<span class="ar-badge ar-badge-design">Designed example</span>

Judge against the entire table, commit history, ownership policy and transaction state, including hidden rows. Canonicalize row order without changing query results. Record `Bottom(duplicate_key)` on an invalid insert and `Unknown(fuel)` when the fixed budget is exhausted. Charge the exact layer-0 calls after any promoted definition is unfolded.

A filtered row view cannot substitute for full-state equivalence.
</section>
</div>

### Contract checklist

| Declare | Specify and test |
| --- | --- |
| Values and bounds | Types for keys, rows, log entries, users; finite key/value sets; maximum rows, turns, and fuel. No unbounded streams. |
| Given atoms | Object constructors and valid/canon functions; operation inputs, outputs, costs and failure reasons; allowed kernel nodes. |
| Inventions | Declare `open_kinds` explicitly; check dependencies and reject closed kinds. Python implements law, bridge and template checks, but this designed SQL world has no runnable declaration or evidence. |
| Visibility | Allowed probes and channels for each user, including errors, renders, traces, steps, feedback, and memory. A full-state judge view stays separate. |
| Evidence | Exact check method and domain, independent reference comparison, definition/world hashes, layer-0 cost and scope-carrying promotion contract. Seed sampled tests but never promote from samples alone. |
| Reproduction | Versioned schema and state codec, fixed generator seeds and moves, split IDs, oracle revision and golden traces. |

**Reference-system cross-check, planned:** for each finite transaction sequence, run the identical operation sequence against an isolated SQL engine in a pinned version. Compare committed rows, rollback behavior, order-insensitive query results, and error classes with the Opulse adapter. Explicitly reconcile SQL null, transaction isolation, and order semantics before claiming equivalence. A difference is a failing test, not a reward to average away. A RISC-V adapter is another candidate research track, not a shipped world.

### Inspect an existing declaration

The source checkout contains a circuits declaration and tests. This site has not checked whether its constructors succeed on your checkout.

- `worlds/decl/v2/circuits@1.json`: declaration schema.
- `src/opulse/worlds_v2/circuits/world.py`: given atoms.
- `tests/worlds_v2/circuits/test_wv2_circuits_depth.py`: finite oracle and promotion tests.

Run `new_library()` and `build_depth_library()` [from the source checkout](index.md#optional-inspect-the-circuits-source) to see their status with your core revision. **Circuits build status: not published.** The [published circuits export](../assets/data/worlds_v2/circuits.json) is a historical export, not a constructor test. Use the [core-only quickstart](index.md) for a runnable example. The proposed SQL-style contract above is not a working command. **Planned:** a public world-builder command.

<p class="ar-next" markdown="1">NEXT / [Run quickstart](index.md) &nbsp; [Design an audit](../research/protocols.md) &nbsp; [Browse worlds](../worlds/index.md)</p>

</div>
