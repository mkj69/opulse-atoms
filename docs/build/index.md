# Build / Quickstart

<link rel="stylesheet" href="../assets/css/atoms2-research.css">
<script defer src="../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

<p class="ar-kicker">BUILD / 01 &nbsp; QUICKSTART</p>

## Run a definition, then inspect a boundary

Clone the repository, install the project's Python dependencies with `python -m pip install -e .`, and run the code below from its root. This example uses a local core operation; it does not load a published world. It parses and prints a declaration, evaluates it under two fuel limits, then runs a fixpoint combinator. See the [installation instructions](https://github.com/mkj69/opulse-atoms#install) for setup.

<div class="ar-callout" markdown="1">
<span class="ar-badge ar-badge-executable">Executable (core SHA-256 {{ A2_CORE_DIGEST }})</span>

Backed by `tests/test_atoms2_research.py::test_quickstart_printed_output_matches_real_fixture` in this checkout. Run from the repository root with the checkout's Python environment and installed project dependencies. `inc` is a local, bounded layer-0 operation; this example is not a verified world export.
</div>

### 1. Parse, evaluate, and cut the trace

The code below is one command. It creates no files. The local `advance` operation calls the capped `inc` operation twice, so the fixpoint reaches 5 from 0. The machine notation printer forms the fixpoint expression shown in the output; its head and arguments are separated there for readability.
The Python API prints the unchanged ASCII machine storage form; the site displays v3 formulas through a world legend. This local example has no published world legend, so its code and captured output remain machine notation.

```bash
PYTHONPATH=src python - <<'PY'
from opulse.atoms import nodes, notation
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.combinators import combinator_defn, counter_atoms, fix_atoms, fix_spec
from opulse.atoms.kernel import Atom, Defn, DictScope, FnRef, Limits, call

declaration = notation.parse_definition('op advance(x: Int) -> Int = inc(inc(x)) L1')
print('declaration:', notation.print_definition(declaration))
scope = DictScope(
    atoms=[Atom('inc', 1, lambda value: min(value + 1, 5)), *counter_atoms(), *fix_atoms()],
    defns=[Defn(declaration.name, ('x',), declaration.body), combinator_defn(fix_spec())],
)
for fuel in (1, 2):
    run = call('advance', (1,), scope, limits=Limits(fuel=fuel))
    print('advance fuel', fuel, ':', run.outcome, 'layer-0 steps:', run.steps)

expression = nodes.Call('fix', (nodes.Lit(FnRef('advance')), nodes.Lit(0), nodes.Lit(6)))
context = {'kinds': {'fix': 'combinator'}, 'op_arity': {'fix': 1}}
text = notation.print_expr(expression, context)
assert notation.parse_expr(text, context) == expression
print('fixpoint head:', text.split('(')[0])
print('fixpoint arguments:', '(' + text.split('(', 1)[1])
run = call('fix', (FnRef('advance'), 0, 6), scope, trace=True)
print('result:', run.outcome, 'layer-0 steps:', run.steps)
for label, boundary in (('closed', Boundary.unfold_none()),
                        ('open', Boundary.unfold_all())):
    visible = flatten_calls(run.trace, boundary)
    charged = sum(frame.steps for frame in visible)
    assert run.trace.outcome == run.outcome and charged == run.steps
    print(label, 'boundary:', len(visible), 'visible calls;',
          'outcome:', run.trace.outcome, 'charged steps:', charged)
PY
```

Observed output in this checkout:

```text
declaration: op advance(x: Int) -> Int = inc(inc(x)) L1
advance fuel 1 : Unknown(resource='fuel') layer-0 steps: 1
advance fuel 2 : Ok(value=3) layer-0 steps: 2
fixpoint head: @fix[advance]
fixpoint arguments: (0, 6)
result: Ok(value=5) layer-0 steps: 19
closed boundary: 1 visible calls; outcome: Ok(value=5) charged steps: 19
open boundary: 19 visible calls; outcome: Ok(value=5) charged steps: 19
```

`Unknown(fuel)` means the first call stopped after one charged step, not that it produced a correct answer. The fixpoint checks for a stable state and stops at 5. Closing the trace hides 18 calls but preserves its outcome and 19 charged layer-0 steps. This is one executable input, not an exhaustive check of the combinator.

### 2. Run the quickstart test

```bash
PYTHONPATH=src python -m pytest -q tests/test_atoms2_research.py -k quickstart
```

The test executes the command and compares every printed line with the output above. It is a local verification path, not a command to generate new worlds.

### Optional: inspect the circuits source

**Circuits build status: not published.** This site does not run the two circuits constructors during its build, so it does not claim that either succeeds for the checkout that served this page. The source checkout includes `new_library()` and `build_depth_library()`; run both with the command below to see their actual status. The [published circuits export](../assets/data/worlds_v2/circuits.json) does not certify that either constructor succeeds. A public atoms-v2 world-builder command is **planned**. Use the core-only quickstart above for a runnable tutorial.

```bash
PYTHONPATH=src python - <<'PY'
from opulse.worlds_v2.circuits.world import new_library
from opulse.worlds_v2.circuits.story import build_depth_library

for name, constructor in (("new_library", new_library), ("build_depth_library", build_depth_library)):
    try:
        library = constructor()
    except Exception as error:
        print(f"{name}: {type(error).__name__}: {error}")
    else:
        print(f"{name}: built {len(library.definitions)} definitions")
PY
```

### Not yet a command

**Planned:** a public world build/verify CLI for new atoms-v2 declarations. The existing `opulse operators` and `opulse bench` commands are for the published **Legacy-v1** operation-only dialect. Do not use them as proof that this quickstart generated an atoms-v2 world.

<p class="ar-next" markdown="1">NEXT / [Design a world contract](world.md) &nbsp; [Inspect the protocol](../research/protocols.md) &nbsp; [Reference semantics](../reference/index.md)</p>

</div>
