# World declarations (`opulse.world/2`)

One JSON file per world version: `worlds/decl/<world>@<version>.json`. A declaration lists the
layer 0 of a world with the four kinds of atoms (docs/spec/atoms-v2.md, sections 4, 5, 6, 7, 12).

- The 12 published worlds are declared as version 1 in dialect `legacy-v1`. Their content follows
  the published data in `docs/assets/data/worlds/<world>.json` (atoms, settings, domain), never the
  presets in `configs/presets/`. Where the two differ, the published data wins.
- `clock@2.json` is the true clock (spec section 14), dialect `atoms-v2`.
- `computer@1.json` is the computer world v1 (spec section 15), dialect `atoms-v2`.

## File layout

```json
{
  "schema": "opulse.world/2",
  "world": "integer",
  "version": 1,
  "dialect": "legacy-v1",
  "title": "Integers",
  "source": {"published": "docs/assets/data/worlds/integer.json",
             "settings": {"<published settings key>": "<published value>"}},
  "params": {},
  "constants": {},
  "objects": [ObjectSpec, ...],
  "operations": [OperationSpec, ...],
  "combinators": {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                  "library": [], "recursion": "legacy"},
  "observation": {"truth": null, "probes": [],
                  "capabilities": {"learner": {"channels": ["results", "errors", "renders", "traces", "steps", "memory"], "probes": "all"}},
                  "show": {"input": "values", "result": "value"},
                  "judge_view": "full_state"},
  "codec": {"legacy_tags": {"int": "int", "nan": "Bottom"}},
  "lock": {"host_digests": {"<operation or object name>": "<sha256>"},
           "constants_hash": "<sha256>", "world_hash": "<sha256>"}
}
```

### ObjectSpec (spec 4)

```json
{"kind": "object", "name": "int", "form": "given",
 "base": null, "tags": null, "group": [], "valid": null, "canon": null,
 "sealed": false, "interface": [], "params": [], "equality": "canonical",
 "canon_cost": "counted", "body": null,
 "host": {"repr": "Python int", "codec": "module:qualname or a short description"},
 "doc": "one sentence"}
```

- `form`: `given` (a layer-0 sort with a host representation and codec), `compose`, `refine`,
  `constant`.
- `tags` (compose): `{"<tag>": {"<field>": "<sort>"}}`, or `{"<tag>": {"items": "<sort>"}}` for a
  variable-length sequence.
- `valid`, `canon`: a node in the JSON of `opulse.atoms.nodes.to_json`, or a host rule
  `{"host": "module:qualname", "digest": "<sha256>"}` (allowed only at layer 0), or `null`.
- `params`: static parameters such as `"T"` or `"n:int"`.

### OperationSpec (spec 5)

```json
{"kind": "operation", "name": "add", "symbol": "+", "role": "combine",
 "inputs": [{"name": "a", "sort": "int", "enter": "bottom"},
            {"name": "b", "sort": "int", "enter": "bottom"}],
 "output": {"sort": "int", "enter": "bottom"},
 "rule": "a + b is integer addition.",
 "errors": ["overflow"],
 "impl": {"host": "opulse.some.module:function", "digest": "<sha256 of inspect.getsource>"},
 "cost": 1, "strict": true, "reads_params": []}
```

- `role`: `transform | combine | decide | relate | act`.
- `enter`: `bottom | normalize | saturate(lo,hi) | fold(<name>)` (spec 4.3, 13.2).
- `errors`: the `Bottom` reasons the operation can return (spec 3), as short identifiers.
- `rule`: required, the human-readable rule (the published `rule` text for legacy worlds).
- `symbol`: the published symbol (legacy worlds); optional for new worlds.

### Observation (spec 7)

`truth` is the sealed full-state sort (`null` when a world has no hidden state). Each probe is
`{"name", "sort", "reads": "<truth sort>", "reveals": ["..."], "impl": {...}}`. A probe is also
listed under `operations` with role `decide` (or `transform`) when the published data calls it as
an atom; the two entries must agree.

## Lock

`lock.host_digests` holds the sha256 of the source (`inspect.getsource`) of every host function
named by an `impl` or a host `valid`/`canon`. `lock.world_hash` is the sha256 of the canonical
JSON (sorted keys, separators `(",", ":")`) of the file without the `lock` member.
`PYTHONPATH=src python -m opulse.tasks_v2.decl --lock` rewrites the locks; the tests fail when a
lock is stale.
