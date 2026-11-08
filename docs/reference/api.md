# API and CLI

<link rel="stylesheet" href="../../assets/css/atoms2-research.css">
<script defer src="../../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

The `opulse.atoms` Python package implements the `{{ A2_SPEC_VERSION }}` core interface described in the [versioned specification](spec.md). The older `opulse.World` and the generated `api/` leaves describe **Legacy-v1** operator-only workflows, not the atoms-v2 definition pipeline. The Python core parses and checks law (`#name`) and bridge (`~name`) definitions; the browser examples do not invoke those checks. See [semantics](index.md) before mixing dialects.

## Versioned records

- `opulse.value/2`: `opulse.atoms.values.encode` / `decode`. Integers use `{"t":"int","v":17}`; strings use `{"t":"str","v":"road"}`; cards use `t`, `tag`, `f`.
- `opulse.world/2`: `opulse.atoms.world.WorldDecl`. Holds the world, version, dialect, params, constants, objects, operations, combinators, observation and lock.
- `opulse.definition/2`: `opulse.atoms.spec.Definition`. Holds a typed definition, body, evidence and status.
- `opulse.world_v2_export/1`: world files under `docs/assets/data/worlds_v2/*.json`, excluding `index.json`. Each site export has a world declaration and design metadata; **not** a checker result.
- `opulse.world_v2_index/1`: `docs/assets/data/worlds_v2/index.json`. The world catalogue index, not a world declaration export.

Dispatch by `schema`. The card form is `{"t":"<sort>","tag":"<tag>","f":[...]}`. Legacy `t`/`v` data needs a world-context codec; its tag alone is not an atoms-v2 card. A world declaration's `dialect` is `atoms-v2` or `legacy-v1`. `WorldDecl.from_dict` checks the schema; exports have `schema`, `world`, `version`, `decl` and additional metadata. Do not infer evidence from an export.

## Atoms-v2 Python

These imports name existing entry points, not a runnable world fixture:

<span class="ar-badge ar-badge-executable">Executable</span>

The imports are defined by the versioned `src/opulse/atoms/` package in the source checkout.

<p class="ar-scroll-cue">Scroll the code sideways to see every import.</p>

```python
from opulse.atoms.boundary import Boundary
from opulse.atoms.kernel import Atom, Defn, DictScope, Limits, evaluate
from opulse.atoms.nodes import Call, Lit
from opulse.atoms.values import Bottom, Ok, Unknown, decode, encode
from opulse.atoms.world import WorldDecl
```

`evaluate(node, env, scope, limits, trace, dialect)` returns a `Run` with `outcome`, `steps`, `jumps` and optional `trace`. `Boundary.unfold_all()` and `Boundary.unfold_none()` select which definitions open in a trace; `Boundary.from_cut()` adapts the legacy operator-only cut. `WorldDecl.from_dict`, `to_dict` and `world_hash()` work with world declarations. [`opulse.atoms.laws`](https://github.com/mkj69/opulse-atoms/blob/main/src/opulse/atoms/laws.py) implements `check_law`, `verify_law`, `rewrite` and `replay_rewrite`; [`opulse.atoms.bridges`](https://github.com/mkj69/opulse-atoms/blob/main/src/opulse/atoms/bridges.py) implements `check_bridge`, `verify_bridge` and `bridge_defn`. These Python checks require a library, declared domain and evidence scope; the designed declarations on [semantics](index.md) have not been run. Consult the [versioned specification](spec.md) for the supported version.

## Legacy-v1 CLI and configuration

<span class="ar-badge">Legacy-v1</span>

No atoms-v2 CLI is published here. These commands serve the older operator-only workflow. `opulse --help` lists installed commands. `opulse atoms export`, `opulse operators`, `opulse verify` and `opulse bench` belong to the published operator and data workflows. Consult `docs/reference/cli.md` and `docs/reference/configuration.md` in the repository for historical options and defaults. Do not pass an atoms-v2 world export to a legacy command unless it explicitly supports the schema. For the existing setup path use the [core-only quickstart](../build/index.md).

## Clock input: what changed from v1 to v2

<span class="ar-badge">Legacy-v1</span>

The committed [clock world export](../assets/data/worlds/clock.json) has a golden case: `add(11, 3)` expects `2`. `KernelEngine` loads the published `Legacy-v1` registry.

<span class="ar-badge ar-badge-executable">Executable</span>

Run this from the repository root with `PYTHONPATH=src`. The separate `clock@2` declaration in `worlds/decl/clock@2.json` supplies the hour entry rule. The v2 calls run the declared `add` through its input edges, so each input is reduced to an hour on entry.

```python
import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms.golden import KernelEngine, iter_cases
from opulse.tasks_v2 import templates

source = Path("docs/assets/data/worlds/clock.json")
world = json.loads(source.read_text(encoding="utf-8"))
case = next(case for case in iter_cases("clock", main_only=True)
            if case.kind == "atom_example" and case.operator == "add")
engine = KernelEngine()
state = engine.load(world)
actual = engine.run(state, case).output
assert actual == case.expected_output
print("published add(11, 3):", actual)
print("legacy add(14, 0):", engine.run(state, replace(case, inputs=(14, 0))).output)

clock = templates.library("clock@2")
add = next(operation for operation in clock.world.operations if operation.name == "add")
assert all(edge.sort == "hour" and edge.enter == "normalize" for edge in add.inputs)
for inputs in ((14, 0), (11, 3)):
    result = clock.run("add", inputs).outcome
    print(f"v2 add{inputs}:", result.value.fields[0])
```

Output from this fixture, recomputed in `tests/test_site_ascii.py`:

```text
published add(11, 3): 2
legacy add(14, 0): 2
v2 add(14, 0): 2
v2 add(11, 3): 2
```

The first line checks the published case against its committed expected output. The second evaluates an additional input with the legacy registry; it is not a golden case. The v2 lines run the declared operation: 14 enters as hour 2, so add(14, 0) is 2, and add(11, 3) wraps to 2. They are live runs, not a regenerated v2 golden fixture.

The declared v2 hour in `worlds/decl/clock@2.json` is a refined integer, and each `add` input has `enter: normalize`. Section 14 of `docs/spec/atoms-v2.md` specifies the same rule. The run uses the clock world's declaration, not the designed template declaration `obj Hour = Quot[Int, mod12] given`.

[Next: Glossary](glossary.md) | [Claim sources](provenance.md)

</div>
