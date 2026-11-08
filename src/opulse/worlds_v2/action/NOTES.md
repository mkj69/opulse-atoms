# Sealed maze robot (action@2)

Layer 0 contains three locked 12x10 mazes, a sealed robot starting at (1,1,E),
turns, a forward move that returns `Bottom(blocked)`, front-wall/front-water
probes, public pose/odometer, and `stats` (public aggregate counters). The only
terrain-reading hosts are `front_wall`, `front_water` and the movement validator
`forward`. The remaining hosts are generic constructors, projection, sequence,
association-list, sorting, comparison and small-integer primitives. All host
atom calls cost one layer-zero step. The host map is for the judge and for the
independent reference oracle, not for the invented definitions.

| Design layer | Invented definition | Kind | Computed layer | M1 example steps | Verification domain |
| --- | --- | --- | --- | --- | --- |
| 1 | `front_clear` | observation | 1 | 2 | 52 real M1 poses and their granted probes |
| 2 | `safe_step` | operation | 2 | 3 | 52 real poses |
| 3 | `Scan` | object | 1 | 1 | 52 coordinate/face tuples |
| 4 | `sense` | operation | 1 | 2 | 52 real poses |
| 5 | `scan` | combinator | 2 | 53 | 52 real poses, both turning directions |
| 6 | `Known` | object | 1 | 1 | 52 coordinates and map values |
| 7 | `merge_scan` | operation | 2 | 70 | 52 real scans of distinct poses |
| 8 | `frontier` | observation | 1 | 48 | 52 scanned known maps |
| 9 | `route_known` | operation | 1 | 108 | 52 known maps and positions |
| 10 | `follow` | combinator | 1 | 92 | 52 poses, forward and safe_step slots |
| 11 | `explore` | combinator | 3 | 416263 | all 64 sparse 2x4 mazes, forward and safe_step slots |
| 12 | `Atlas` | object | 1 | 416264 | 64 completed sparse surveys |

The example values and three showcase answers are checked against
`worlds/catalogue/depth/action.py`; showcase answers are also computed from
the kernel's surveyed atlas and route-finding. The 60-scan M1 exploration
uses 70 forward moves, 283 turns, and 533 measured kernel front-probe calls.
The earlier 760 was an estimate of calls that included short-circuited probes.
The tests separately compare all reachable
cells, scan records and explored results on M1, M2 and M3. A blocked northward
safe step is exported as the kernel-run failure example. The scope described
by each promoted card is deliberately the actual checked sample, not an
unsubstantiated exhaustive claim over all 12x10 maps.
The `safe_step` and `sense` examples use distinct M2 and M3 poses; the
design fixes the M1 identity and exact coordinates in the later scan, route,
follow, and exploration values, so those cards cannot change mazes without
breaking the required example values. Each exported expression binds its
named input arguments to the encoded values without printing a maze map.

## Design adaptations and open issues

- `scan_default` is an additional invented operation that plugs `turn_right`
  and `sense` into the rank-2 `scan` combinator, which `explore` accepts as
  a unary operation slot. `make_known` and `make_atlas` are separate invented
  builder operations; the tower's `Known` and `Atlas` are core-generated
  parameterized compose objects, not callable object bodies.
- The design presents `make_known` and `make_atlas` as object interfaces;
  the core requires separately named builder operations to assemble their
  validated inputs. Their computed layers are 2 rather than 1 and 2,
  respectively; `merge_scan` is layer 2 because it calls `Known.known`.
- Computed dependency layers are lower than the design's presentation layers
  for definitions that consume a `Scan` or `Known` as a data argument rather
  than statically calling its constructor. The export keeps both values.
- Sparse evidence mazes have 2x4 interior positions with at most three
  additional free cells; each unique pattern has a free start. These are
  declared as the 64 mask IDs between E000 and E112 with at most three set bits,
  and generated deterministically in both host and independent reference maps.
  Runnable layouts for these and M1/M2/M3 are in `worlds/judge/action.json`.
  The three locked full-size mazes are independently checked by regular tests.
- `stats` is a given operation rather than a declared probe because the
  declaration validator requires every probe's `reads` to equal the one
  truth sort (`Bot`), whereas `stats` must read a `Survey`.
- The declaration validator cannot accept top-level `title_zh` or
  `open_kinds`; both are supplied in the export. Layer-0 `@seq` is a
  declaration-provided `CombinatorSpec` with a public kernel-substitution body.
- **ADAPTER:** `adapter.py` keeps sealed constructors, the `frontier` observation
  over a `Known` subject, and full exploration on world-specific finite domains.
  Core verification now handles the other observation, operations, the `scan` and
  `follow` operation families, the `Atlas` compose object, and template instances.
  The local FnRef JSON codec, redundant probe wrappers, and generic
  compose-object verifier are removed;
  the core codec handles operation references and measured constructors remain
  checked against the exact world-specific fields.
  Local evidence is bound to the digest of every input tuple actually checked.
  Core compose finite-values checking cannot construct arbitrary cross-products
  of measured Scan faces or mutually consistent Known fields; core observation
  checking rejects `Known` as an ungranted probe for `frontier`. The `explore`
  combinator's forwarded `step` slot is rejected by the generic checker, and
  its independently measured probe counts differ from the reference model.
  The
  `explore` loop is a bounded fixpoint-until-no-frontier expressed by `Rec`
  and a public kernel body rather than the planned standard fixpoint mode.
- Generic `card` cannot mint `Scan`, `Known`, `Survey`, or `Atlas`.
  Host-issued bots carry value-based seals, scans require four measured faces,
  and completed surveys carry authenticated probe counts in immutable fields.
  `Library.run` rejects malformed invented values and direct survey minting;
  copied completed surveys remain valid. A trusted Python host is the seal issuer.
  The public export
  redacts complete surveys; judge data lives in its own artifact.
- `?Count[probe]` is instantiated through `opulse.atoms.templates` for
  `front_wall` and `front_water`; each history observation is independently
  checked and promoted on four M1 poses. The template remains written because
  the core template checker rejects the generated template-origin call in an
  observation as a non-observation dependency.
- Cards 3, 4, 6, 8-10, and 12 consume lower-layer data rather than call their
  immediately preceding card; `def_layer` reports actual dependency depth.
- All twelve exported tower example step counts remain unchanged on the newer
  core. Core observation verification records two steps per `front_clear`
  sample, rather than the previous local mean of 1.5961538461538463;
  its 52-pose scope, example steps and displayed value remain unchanged.

The tower retains the original design text in `design_decl`. None of its
stored definitions currently print and re-parse to the same body, so no story
row publishes `decl` or `ascii`; `body_sha256` binds the real stored body.
Definitions, evidence, and evaluated examples are unchanged.

The following example texts cannot be written as the **same evaluation** in
context-free `notation.parse_expr` grammar, so they remain unmarked by `ascii`:
`action-3` (`Scan.scan`), `action-5` (`@scan`), `action-6`
(`Known.known`), `action-10` (`@follow`), `action-11` (`@explore`),
`action-12` (`Atlas.atlas` around `@explore`). Constructor calls require a
dotted interface-call syntax that `parse_expr` does not accept; combinator
sigils require a context mapping and operation-reference slots that the shared
export's context-free parser does not supply. The robot's sealed `Bot` values
also cannot be faithfully constructed by a parsed literal (their tags contain
a seal delimiter), so the text continues to use the original public pose form.

Full-scope sealed-map and evidence-domain re-checks run with
`OPULSE_RUN_SLOW=1`; the default tests still build and audit the promoted
library and compare the generated export to the committed JSON. The export stores
an elided call tree for the deep example, with
exact step counts preserved. The Atlas example executes the nested exploration
printed in its expression (416264 steps including Atlas construction).
The action library validates bounded coordinates, measured Scan faces, sorted
Known evidence, and authorized Atlas survey provenance at the compose boundary.
# Source printing

- front_clear: printer unavailable — bool cards are indistinguishable from host bools in ASCII.
- safe_step: printer unavailable — operation metadata has no compact ASCII declaration.
- Scan: printer unavailable — unsupported compose metadata.
- sense: printer unavailable — operation metadata has no compact ASCII declaration.
- scan: printer unavailable — invalid ASCII identifier.
- Known: printer unavailable — unsupported compose metadata.
- merge_scan: printer unavailable — invalid ASCII identifier.
- frontier: printer unavailable — invalid ASCII identifier.
- route_known: printer unavailable — operation metadata has no compact ASCII declaration.
- follow: printer unavailable — printed source re-parses to a different body.
- explore: printer unavailable — printed source re-parses to a different body.
- Atlas: printer unavailable — unsupported compose metadata.
