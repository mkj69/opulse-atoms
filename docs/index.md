---
hide:
  - navigation
  - toc
---

<link rel="stylesheet" href="assets/css/atoms2-roads.css">
<link rel="stylesheet" href="assets/css/atoms2-first-tower.css">

# Invent the pieces; then build with them.

In a finite world, invent objects, operations, ways to combine them, and observations. Reuse them in later layers with a checkable record. Worlds can also open laws and bridges.

[See how it grows](learn/){ .md-button .md-button--primary } [Try a challenge](play/challenge/){ .md-button }

[Browse worlds](worlds/) | [Research uses](research/)

<section class="roads-card" data-roads-home aria-label="Is the road route optimal?">
<p class="roads-eyebrow">A route across 12 junctions, built from five core-run definitions</p>
<h2>A valid route can still be wrong.</h2>
<p class="roads-badge"><span data-roads-badge>See the core run artifact for the check scope</span></p>
<p>The <a href="assets/data/atoms2/roads_core.json">roads core run artifact</a> records the bounded check scope. The larger Metro run is a separate call outside that checked scope. The browser separately checks the public Metro map.</p>
<p><span data-roads-optimal>The optimal-route observation</span> asks whether the A-to-L route through A, D, F, H, K and L is cheapest.</p>
<div class="roads-player"><div class="roads-chain" data-roads-chain aria-label="Five definitions in presentation order"></div><p data-roads-step>Loading road steps...</p><span data-roads-position></span><p data-roads-answer hidden>Answer: false. This route is valid, but a cheaper route exists.</p></div>
<div class="roads-controls"><button class="a2-btn" type="button" data-roads-next>Next recorded step</button> <button class="a2-btn" type="button" data-roads-play>Play recorded steps</button> <a href="learn/">See all dependencies</a></div>
<p>Five definitions, shown in order. Each recorded core run is separate from its definition evidence; badges require recorded checked-input scopes.</p>
<ol class="roads-dependency-list" data-roads-home-deps aria-label="Core-run road definitions"></ol>
<p>Compare two routes step by step.</p>
<div class="roads-map-and-notes">
<div class="roads-map-wrap roads-map-home" data-roads-map aria-label="Metro map: the asked route A,D,F,H,K,L costs 12; the best route A,D,G,I,K,L costs 11"></div>
<div class="roads-map-notes">
<p><strong>Start A / destination L</strong></p>
<p>Asked route: <code>A,D,F,H,K,L</code>. Cost: 12.</p>
<p>Cheapest route: <code>A,D,G,I,K,L</code>. Cost: 11.</p>
<p class="roads-computed" data-roads-result hidden>Core and browser comparison loading.</p>
<p><strong>Why the answer changes:</strong> both routes reach L, but the dashed route costs one less.</p>
<p class="roads-map-cue">Scroll the map sideways to reach L.</p>
<p><a href="play/challenge/">Try this step: find the worst two-road closure</a></p>
</div>
</div>
</section>

<section class="first-tower" aria-label="Integer tower, run on the core">
<h2>A second, independent tower: integer and fractions</h2>
<p class="first-tower-intro">This tower shows fraction multiplication and a failed construction. A fraction with a zero denominator fails as invalid. Natural numbers feed repeat, then multiplication and fraction multiplication. Fractions also feed fraction multiplication. The seen-value observation reads the result through the granted value probe. It does not call fraction multiplication. Outcomes come from core runs at build time. <a href="worlds/integer/">Explore the integer world</a>.</p>
<div data-a2="first-tower" data-src="assets/data/atoms2/first_tower.json" aria-label="Interactive core-run integer tower"></div>
<ol class="first-tower-fallback" data-first-tower-fallback aria-label="Integer tower summary without JavaScript">
<li>L1 Core summary: Natural numbers keep nonnegative integers. <span class="first-tower-badge">Bounded (61 cases)</span></li>
<li>L2 Core summary: Repeat applies a supplied operation to a seed the requested number of times. Uses Nat. <span class="first-tower-badge">Bounded (50 cases)</span></li>
<li>L3 Core summary: Multiplication counts ticks, adds the left magnitude once per tick, and negates the result when input signs differ. Uses Nat, @repeat. <span class="first-tower-badge">Bounded (169 cases)</span></li>
<li>L1 Core summary: Fractions reject a zero denominator and reduce numerator and denominator with a consistent sign. <span class="first-tower-badge">Bounded (169 cases)</span></li>
<li>L4 Core summary: Fraction multiplication multiplies the numerators and denominators, then constructs a reduced fraction. Uses Frac, mul. <span class="first-tower-badge">Bounded (100 cases)</span></li>
<li>L1 Printed from the core definition (re-parses: yes): <code>obs ?seen_value{value} = ?value{value} L1</code>. <span class="first-tower-badge">Bounded (21 cases)</span></li>
<li><code>Frac&lt;1, 0&gt;</code> <span class="first-tower-badge">Executable (core run artifact)</span> returns <code>Bottom(invalid)</code> through the core.</li>
</ol>
<p>Each row has bounded evidence from the <a href="assets/data/atoms2/first_tower.json">versioned run artifact</a>. The prose summaries describe these core definitions, not the longer twelve-card <a href="worlds/integer/">story design text</a>. Only the printed row is pasteable source.</p>
</section>

<style>
.op-poster { display: block; width: min(100%, 38rem); margin: 2rem auto; border-radius: 12px; overflow: hidden; }
.op-poster img { display: block; width: 100%; height: auto; }
body[data-md-color-scheme="slate"] .op-poster-light,
body:not([data-md-color-scheme="slate"]) .op-poster-dark { display: none; }
</style>
<div class="op-poster">
<img class="op-poster-light" src="assets/video/poster-light.jpg" alt="Opulse logo and the words 'Finite atoms, endless concepts. Every step of reasoning, in plain sight.'" loading="lazy">
<img class="op-poster-dark" src="assets/video/poster-dark.jpg" alt="Opulse logo and the words 'Finite atoms, endless concepts. Every step of reasoning, in plain sight.'" loading="lazy">
</div>

<script src="assets/js/atoms2/roads.js"></script>
<script src="assets/js/atoms2/first-tower.js"></script>
