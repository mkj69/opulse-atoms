# Semantics

<link rel="stylesheet" href="../assets/css/atoms2-research.css">
<link rel="stylesheet" href="../assets/css/atoms2-boundary.css">
<link rel="stylesheet" href="../assets/css/atoms2-modes.css">
<script defer src="../assets/js/atoms2/research-ui.js"></script>
<script defer src="../assets/js/atoms2/boundary.js"></script>
<script defer src="../assets/js/atoms2/modes.js"></script>

<div class="ar-page" markdown="1">

Read the six-kind grammar below. The [notation v3 reference](notation-v3.md) explains the display and copy spellings; the [versioned specification](spec.md) records the implemented subset (`{{ A2_SPEC_VERSION }}`). See [provenance](provenance.md) for the core SHA-256 of this build. The Python core implements laws, bridges and templates. Meta quote/eval remains a design proposal. The [Legacy-v1 reference](#legacy-v1-reference) documents a separate operator-only interface.

**Find a rule:** [Six kinds](#six-kinds) | [Typed expressions](#typed-expressions) | [Evaluation](#evaluation-and-accounting) | [Invariants](#four-invariants) | [Combination modes](#combination-modes) | [Templates and meta](#templates-and-meta).

## Six kinds

A world declares its layer 0 as given; later definitions depend on earlier layers. Each world decides which kinds are open to invention. A mark is one glyph plus an index: suits and shapes for operations, double-struck capitals for objects, Greek capitals for combinators, hatted capitals for observations, `≡` for laws and `↝` or `⇝` for bridges. A template retains its kind's mark and takes atom parameters in brackets; new kinds can use `◈` with a kind-number superscript. These shapes identify kinds without relying on color.

Digits starting 1 to 9 mean a defined atom; digits starting with 0 number an overflow given when a kind runs out of unindexed glyphs; a letter means a parameter slot; no index means a given; a splice index `⌞e⌟` names the atom computed by `e`. A left superscript on a signature mark gives its layer; a prime on an observation reads its previous value. Each world has a legend mapping marks to names, kinds and signatures. The fixed symbol-to-ASCII map does not depend on that legend.

A mark can sit between two values, before one value or after it. Parentheses group compound operands; a mark binds more tightly than an arithmetic or comparison sign. A mark followed by `( )` takes values, `[ ]` takes atoms, and `⟨ ⟩` takes hidden state. Brackets immediately after a mark belong to that mark, regardless of spaces. `=` defines, `==` compares, `⇒` gives a result, `:` introduces a signature, and `⊢` attaches a checked condition. A law mark between expressions is one rewrite step. Objects use `∈` and `∣` to refine a set, `×` for product, and `↾` to seal an interface; `⌜ ⌝` quotes a definition.

| Kind | Display mark | ASCII family | Example use |
| --- | --- | --- | --- |
| Operation | <code class="n3" data-n3-ascii="\dia_6">♦₆</code> | `\dia_6` | <code class="n3" data-n3-ascii="a \dia_6 b">a ♦₆ b</code> |
| Object | <code class="n3" data-n3-ascii="\bbD_1">𝔻₁</code> | `\bbD_1` | <code class="n3" data-n3-ascii="\bbD_1(2, 4)">𝔻₁(2, 4)</code> |
| Combinator | <code class="n3" data-n3-ascii="\Theta_1">Θ₁</code> | `\Theta_1` | <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3">Θ₁[♡₄₅] 3</code> |
| Observation | <code class="n3" data-n3-ascii="\hatO_1">Ô₁</code> | `\hatO_1` | <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt;">Ô₁⟨s⟩</code> |
| Law | <code class="n3" data-n3-ascii="\eqv_1">≡₁</code> | `\eqv_1` | <code class="n3" data-n3-ascii="(3 \spade_3 5) \eqv_1 (5 \spade_3 3)">(3 ♠₃ 5) ≡₁ (5 ♠₃ 3)</code> |
| Bridge | <code class="n3" data-n3-ascii="\squig_1">↝₁</code> | `\squig_1` | <code class="n3" data-n3-ascii="\squig_1(m)">↝₁(m)</code> |

The [full table](notation-v3.md) lists every family. These worked examples use the [C-example legend](notation-v3.md), not names assigned by a live world:

| Example | Display | v3-ASCII | Reading |
| --- | --- | --- | --- |
| C1 | <code class="n3" data-n3-ascii="a \dia_6 b = { (a @) * b }">a ♦₆ b = { (a @) * b }</code> | `a \dia_6 b = { (a @) * b }` | Defines an operation using a given reversal and multiplication. |
| C3 | <code class="n3" data-n3-ascii="a ^1\spade_3 b = { 0, if b == 0; a + (a \spade_3 (b - 1)), else }">a ¹♠₃ b = { 0, if b == 0; a + (a ♠₃ (b - 1)), else }</code> | `a ^1\spade_3 b = { 0, if b == 0; a + (a \spade_3 (b - 1)), else }` | A layer-1 recursive multiplication definition. |
| C8 | <code class="n3" data-n3-ascii="\Theta_1&#91;\dia_a&#93; x = { \dia_a (\dia_a x) }">Θ₁[♦ₐ] x = { ♦ₐ (♦ₐ x) }</code> | `\Theta_1[\dia_a] x = { \dia_a (\dia_a x) }` | The slot supplies an operation used twice. |
| C9 | <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3 =&gt; 12">Θ₁[♡₄₅] 3 ⇒ 12</code> | `\Theta_1[\wheart_45] 3 => 12` | Instantiates the combinator with a defined operation. |
| C11 | <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt; = { not \hatW&lt;&#124;s&#124;&gt; and not \hatU&lt;&#124;s&#124;&gt; }">Ô₁⟨s⟩ = { not Ŵ⟨s⟩ and not Û⟨s⟩ }</code> | <code>\hatO_1&lt;&#124;s&#124;&gt; = { not \hatW&lt;&#124;s&#124;&gt; and not \hatU&lt;&#124;s&#124;&gt; }</code> | Reads a hidden state through two granted probes. |
| C14 | <code class="n3" data-n3-ascii="\eqv_1 : \all a, b \in \bbZ. a \spade_3 b == b \spade_3 a">≡₁ : ∀ a, b ∈ ℤ. a ♠₃ b == b ♠₃ a</code> | `\eqv_1 : \all a, b \in \bbZ. a \spade_3 b == b \spade_3 a` | States a law whose check needs a declared scope. |
| C15 | <code class="n3" data-n3-ascii="\squig_1 : \bbS_6 -&gt; \bbG_7 &#124;- \hatI_3&lt;&#124;\squig_1(m)&#124;&gt; == \hatJ_4&lt;&#124;m&#124;&gt;">↝₁ : 𝕊₆ → 𝔾₇ ⊢ Î₃⟨↝₁(m)⟩ == Ĵ₄⟨m⟩</code> | <code>\squig_1 : \bbS_6 -&gt; \bbG_7 &#124;- \hatI_3&lt;&#124;\squig_1(m)&#124;&gt; == \hatJ_4&lt;&#124;m&#124;&gt;</code> | A bridge condition comparing two observations. |

**Storage form.** The following are illustrative machine declarations, not v3 display formulas. The Python core parses law (`#name`) and bridge (`~name`) declarations; this page does not run their checks in the browser.

<span class="ar-badge ar-badge-design">Designed example</span>

The six declarations are illustrations, not checked examples. The ASCII machine notation is preserved here for parser users.

- **Object:** `obj Frac = Quot[Pair<Int, Int>, reduce] L2` gives `Frac<1, 2>`, a typed value.
- **Operation:** `op cost(r: Route) -> Int = sum_weights(r) L2` gives `cost(route)`, a computed value. In the roads world, `cost` adds the road weights along a route (12 for A, D, F, H, K, L); its recorded body reads the route's graph and vertices through member operations that the ASCII printer cannot print yet, so this line is a schematic.
- **Combinator:** <code data-a2-expr>comb @twice&#91;step: A -&gt; A&#93;(state: A) -&gt; A = step(step(state)) L4</code> gives <code>@twice[step]&#40;state&#41;</code>, two applications in this illustration.
- **Observation:** `obs ?top{body} = ?visible{body} L2` gives `?top{body}`, a read of a permitted probe if that probe is granted.
- **Law:** `law #mul_comm: eq(mul(a, b), mul(b, a)) for a: Int, b: Int L3` illustrates a rewrite declaration; `by #mul_comm` needs a separate scope check.
- **Bridge:** `bridge ~to_frac: MyFrac -> Frac = make(x) L4` gives `~to_frac(x)`, a proposed translation.

[`opulse.atoms.laws`](api.md#atoms-v2-python) checks a law on a declared domain and replays a promoted rewrite against its scope and layer-0 outcome. [`opulse.atoms.bridges`](api.md#atoms-v2-python) checks translation and interface commutation on a declared domain; inputs outside a partial bridge's domain return `Bottom(outside_domain)`. See the [glossary](glossary.md) for exact spelling.

## Typed expressions

Values are finite `Int`, `Text` or `Card(sort, tag, fields)` trees in the Python API. Objects can compose forms, refine a base with `valid` and `canon`, or seal their representation. The display uses infix defined marks as well as given arithmetic and comparison signs. The machine parser keeps its named calls such as `lt(a, b)` and `eq(a, b)`; they are storage syntax, not the visible notation.

The implemented kernel has `Var`, `Lit`, `Call`, `Let`, ordered `Case`, measured or fuel-limited `Rec`, and `Blocks`/`Jump`. `Call` takes a name and typed arguments; `Let` binds an evaluated outcome; `Case` selects its first true arm. See [`opulse.atoms.nodes`](api.md#atoms-v2-python) for entry points and `docs/spec/atoms-v2.md` in the repository for the node fields.

## Evaluation and accounting

Evaluation returns `Ok(value)`, `Bottom(reason)` for a domain failure, or `Unknown(resource)` for an exhausted budget. `Unknown` never counts as correct. In atoms-v2, arguments evaluate left to right and stop on the first non-`Ok` outcome. A failing evaluated condition aborts `Case`; later arms cost nothing. Observations use only granted probes. A judge uses its declared full-state judge view, not a learner-visible projection or reward.

Charged layer-0 steps count evaluated operations and jumps, plus canonicalization where declared. A promoted definition can appear as one **visible** step without erasing its layer-0 cost. Memoization (reuse of a cached subresult) saves executed work while this kernel charges the same steps as the plain unfolding. An exact cost needs a run and a versioned input, not a count of collapsed trace labels.

## Four invariants

1. A definition unfolds to layer 0 with the same result, including failure and resource behavior under equal accounting.
2. A boundary changes what the trace shows, not the outcome or charged layer-0 cost.
3. Observations never alter facts. The judge compares the declared full-state view.
4. Promotion carries a definition's content identity, contract, verification method and scope. Seeded samples alone never authorize promotion.

## Combination modes

Each panel below replays a real kernel run. Open a definition to see its layer-0 calls. The badge identifies the core revision; these runs are **not** exhaustive verification of the general modes.

<div id="a2-reference-modes" class="a2-reference-modes" aria-label="Four executable combination mode traces"></div>

## Templates and meta

Definitions pass through `written`, `checked`, `callable`, `verified` and, when eligible, `promoted`. Record kind, origin, layer, dependencies, body, evidence, contract and cost.

<span class="ar-badge ar-badge-design">Designed example</span>

In the fixed C6 example, <code class="n3" data-n3-ascii="\bbK_4&#91;\bbX_t, \dia_a&#93; = \bbX_t / \dia_a">𝕂₄[𝕏ₜ, ♦ₐ] = 𝕏ₜ / ♦ₐ</code> is a quotient template; <code class="n3" data-n3-ascii="\bbD_1 = \bbK_4&#91;\bbT_5&#91;\bbZ, \bbZ&#93;, \wdia_9&#93;">𝔻₁ = 𝕂₄[𝕋₅[ℤ, ℤ], ♢₉]</code> is one instance. A checked template family does not automatically verify every instance. Each instance needs separate evidence and can unfold through its template and arguments.

<span class="ar-badge ar-badge-design">Designed example</span>

A proposed code object holds a finite definition; quote captures code and evaluation requires finite fuel. Changing code makes a new content hash and detaches earlier evidence. Promoted definitions remain immutable. The `{{ A2_SPEC_VERSION }}` specification does not certify a quote/eval runner; this paragraph describes a design proposal.

## Legacy-v1 reference

The operator-only `legacy-v1` command line and configuration are separate from the atoms-v2 pipeline. Their command names, settings and symbol options do not define atoms-v2. Start with the [curated API guide](api.md) for versioned atoms-v2 records and migration notes.

[Next: API and CLI](api.md) | [Terms: Glossary](glossary.md)

</div>
