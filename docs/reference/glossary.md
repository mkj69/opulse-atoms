# Glossary

<link rel="stylesheet" href="../../assets/css/atoms2-research.css">
<script defer src="../../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

These terms apply to atoms-v2. Display formulas have a separate v3-ASCII copy spelling. Copying does not verify a designed declaration. The Python core parses and checks laws and bridges, but this table does not run those checks. The [semantics](index.md) give evaluation rules, the [notation reference](notation-v3.md) gives exact symbols, and the [versioned specification](spec.md) describes the implemented subset.

<span class="ar-badge ar-badge-design">Designed example</span>

The illustrative declarations in this table are not verified runs.

<div class="ar-glossary" markdown="1">

| Term | Meaning and spelling |
| --- | --- |
| [Atom](index.md#six-kinds) | A given or invented object, operation, combinator, observation, law or bridge. The old operation-only meaning belongs to `legacy-v1`. |
| [Object](index.md#six-kinds) | A typed value or form, for example <code class="n3" data-n3-ascii="\bbD_1(2, 4)">𝔻₁(2, 4)</code>. It may compose, refine or seal its representation. |
| [Operation](index.md#six-kinds) | A typed computation such as <code class="n3" data-n3-ascii="a \dia_6 b">a ♦₆ b</code>. Given comparisons use binary signs. |
| [Combinator](index.md#combination-modes) | A way to assemble computations, such as <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3">Θ₁[♡₄₅] 3</code>. |
| [Observation](index.md#evaluation-and-accounting) | A read of granted probes or remembered observations, such as <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt;">Ô₁⟨s⟩</code>. It is not hidden truth. |
| [Law](index.md#six-kinds) | A statement checked on its declared input scope, such as <code class="n3" data-n3-ascii="\eqv_1">≡₁</code>; checking 8-bit inputs would not certify all integers. |
| [Bridge](index.md#six-kinds) | A translation checked against its declared interface and domain, such as <code class="n3" data-n3-ascii="\squig_1(m)">↝₁(m)</code>. |
| [Mark](notation-v3.md) | One glyph from a kind family, optionally carrying an index, layer or prime. The example mark <code class="n3" data-n3-ascii="\dia_6">♦₆</code> is an operation. |
| [Index](notation-v3.md) | Digits starting 1 to 9 select a defined atom; digits starting with 0 number an overflow given when a kind runs out of unindexed glyphs; a letter identifies a slot; no index means given; a splice computes the reference. |
| [Slot](notation-v3.md) | An atom parameter, not a value: <code class="n3" data-n3-ascii="\dia_a">♦ₐ</code> stands for an operation passed to a template or combinator. |
| [Given / invented](index.md#six-kinds) | A given is a layer-0 atom; its mark normally has no index, as with <code class="n3" data-n3-ascii="\bbZ">ℤ</code>. Invented definitions have layers 1, 2 and so on. A closed kind cannot be invented in that world. |
| [Splice](notation-v3.md) | A computed atom placed in the mark's index: <code class="n3" data-n3-ascii="\dia{&#124; e &#124;}">♦⌞e⌟</code>. |
| [Layer superscript](notation-v3.md) | A left superscript on a header mark records its dependency layer: <code class="n3" data-n3-ascii="^1\spade_3">¹♠₃</code> is at layer 1. |
| [Legend](notation-v3.md) | A per-world map from marks to names, kinds, layers and signatures. Its assignments do not alter the global display-to-ASCII token mapping. |
| [Display form](notation-v3.md) | The site-facing Unicode spelling of a formula, for example <code class="n3" data-n3-ascii="\dia_6">♦₆</code>. |
| [ASCII storage form](notation-v3.md) | The unchanged machine declarations in exports and datasets. V3-ASCII (`\dia_6`) is a separate, one-to-one copy spelling of the display form, not the machine declaration syntax. |
| [Layer](index.md#six-kinds) | A dependency level. A higher layer can depend on earlier definitions of any open kind, not only operations. |
| [Template](index.md#templates-and-meta) | A typed family such as <code class="n3" data-n3-ascii="\bbK_4&#91;\bbX_t, \dia_a&#93;">𝕂₄[𝕏ₜ, ♦ₐ]</code>; its instances need their own evidence. |
| [Probe / judge view](index.md#evaluation-and-accounting) | A probe is a permitted read interface. The judge view decides correctness from full state, which may be hidden from a learner. |
| [Result / outcome](index.md#evaluation-and-accounting) | `Ok(value)` succeeds, `Bottom(reason)` is a domain failure, and `Unknown(resource)` is exhaustion and never correct. Undefined `NaN` belongs to **Legacy-v1** only. |
| [Reward](index.md#four-invariants) | A task-specific score or projection. Equal rewards do not prove equal full states or outcomes. |
| [Evidence / scope](index.md#four-invariants) | A record of method (`exhaustive`, `bounded`, seeded `sampled`), domain, world version and contract. Scope states exactly what was checked. |
| [Verification / promotion](index.md#four-invariants) | Verification checks the contract on the stated scope. Promotion lets an eligible verified definition be reused as one visible step with that scope; sampling alone cannot authorize it. |
| [Boundary / unfold](index.md#four-invariants) | A boundary selects which definitions to show as one step. Unfolding expands to layer-0 work without changing outcome or charged cost. |
| [Fuel](index.md#evaluation-and-accounting) | A limit on charged layer-0 work. Exhaustion gives `Unknown(fuel)`, not a domain failure. |

</div>

## Observation is not truth

{{ A2_GLOSSARY_COMPARISON }}

<span class="ar-badge ar-badge-design">Designed example</span>

To teach this ambiguity with sealed values, a future world could define a sealed volume object. It could expose only a top-view observation for distinct hidden bodies that share a top view. This extension is **not** in the linked shadows historical export. Design record: shadows world, depth pass (11-04). That record proposes projection-only learner views; the seal is an additional proposal.

[Read the grammar](index.md#six-kinds) | [Inspect claim sources](provenance.md)

</div>
