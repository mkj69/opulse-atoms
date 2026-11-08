# How it grows

A world can open only some kinds for invention. The classic Opulse mode opens operations only; a multi-kind world can also let you invent objects, combinators and observations. A world may open laws and bridges too. The given atoms still work when their kind is closed to invention. [Compare the six kinds](kinds.md) or [filter worlds by open kinds](../worlds/).

The site uses notation v3 for formulas. The [fixed C9 example](../reference/notation-v3.md), <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3 =&gt; 12">Θ₁[♡₄₅] 3 ⇒ 12</code>, shows an operation passed to a combinator. Names in historical artifacts below are ASCII storage identifiers; consult each world's legend before reading its display marks.

<link rel="stylesheet" href="../assets/css/atoms2-roads.css">
<link rel="stylesheet" href="../assets/css/atoms2-first-tower.css">

## One tower: roads from Route to survival

The roads tower spans four kinds: Route is an object, cost and best are operations, failures is a combinator, and survives is an observation. The route and survival questions follow different branches of this same world. The bounded check includes the survival observation. The twelve-junction Metro run, over 277 closures, is outside that checked scope.

<p class="roads-badge"><span data-roads-badge>See the core run artifact for the check scope</span></p>
<p><a href="../assets/data/atoms2/roads_core.json">Core run artifact</a>: the survives observation returns true for the Metro route from A to L with two closures, over 277 closures. A route over a missing road returns a domain failure. The browser independently checks the public graph.</p>

<section data-roads-learn class="roads-learn">
<h2>Which steps does survival use?</h2>
<p>Select a definition to see its core-run outcome, direct prerequisites and any recorded checked-input scope.</p>
<button class="a2-btn" data-roads-survives type="button" aria-pressed="true">Hide survival prerequisites</button>
<p data-roads-deps role="status">Loading survival prerequisites...</p>
<ol class="roads-path" data-roads-path aria-label="Selected definitions with direct prerequisites"></ol>
<details class="roads-inventory"><summary>Explore all twelve designed definitions</summary><ol class="roads-layers" data-roads-layers aria-label="Designed road definitions by layer"><li>Loading layers...</li></ol></details>
<details class="roads-given" data-roads-given><summary>See all eight given atoms (layer 0)</summary><ol class="roads-layers" data-roads-given-layers aria-label="Given road definitions"></ol></details>
</section>

<section class="first-tower" aria-label="Integer tower, run on the core">
<h2>A second, independent tower: integer and fractions</h2>
<p class="first-tower-intro">This tower shows fraction multiplication and a failed construction. A fraction with a zero denominator fails as invalid. Natural numbers feed repeat, then multiplication and fraction multiplication. Fractions also feed fraction multiplication. The seen-value observation reads the result through the granted value probe. It does not call fraction multiplication. <a href="../worlds/integer/">Explore the integer world</a>.</p>
<div data-a2="first-tower" data-learn data-src="../assets/data/atoms2/first_tower.json" aria-label="Interactive core-run integer tower"></div>
<ol class="first-tower-fallback" data-first-tower-fallback aria-label="Integer tower summary without JavaScript">
<li>L1 Core summary: Natural numbers keep nonnegative integers. <span class="first-tower-badge">Bounded (61 cases)</span></li>
<li>L2 Core summary: Repeat applies a supplied operation to a seed the requested number of times. Uses Nat. <span class="first-tower-badge">Bounded (50 cases)</span></li>
<li>L3 Core summary: Multiplication counts ticks, adds the left magnitude once per tick, and negates the result when input signs differ. Uses Nat, @repeat. <span class="first-tower-badge">Bounded (169 cases)</span></li>
<li>L1 Core summary: Fractions reject a zero denominator and reduce numerator and denominator with a consistent sign. <span class="first-tower-badge">Bounded (169 cases)</span></li>
<li>L4 Core summary: Fraction multiplication multiplies the numerators and denominators, then constructs a reduced fraction. Uses Frac, mul. <span class="first-tower-badge">Bounded (100 cases)</span></li>
<li>L1 Printed from the core definition (re-parses: yes): <code>obs ?seen_value{value} = ?value{value} L1</code>. <span class="first-tower-badge">Bounded (21 cases)</span></li>
<li><code>Frac&lt;1, 0&gt;</code> <span class="first-tower-badge">Executable (core run artifact)</span> returns <code>Bottom(invalid)</code> through the core.</li>
</ol>
<p>Each outcome and bounded scope comes from the <a href="../assets/data/atoms2/first_tower.json">core run artifact</a>. The prose summaries describe these core definitions, not the longer twelve-card <a href="../worlds/integer/">story design text</a>. Only the printed row is pasteable source.</p>
</section>

[Continue: kinds of definitions](kinds/){ .md-button .md-button--primary } [Explore Play](../play/challenge/){ .md-button }

<script src="../assets/js/atoms2/roads.js"></script>
<script src="../assets/js/atoms2/first-tower.js"></script>
