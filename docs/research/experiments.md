# Research experiments

<link rel="stylesheet" href="../../assets/css/atoms2-research.css">
<script defer src="../../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

<p class="ar-kicker">RESEARCH / 03 &nbsp; EXPERIMENTS</p>

## Change the boundary. Keep the computation.

The `grammar` design separates strings from their derivation trees. A split operation can feed a reusable parser combinator. The old parse-count sketch reads a parse-count probe; spec 0.5 also permits an observation to apply a pure combinator to observed values. It cannot act or read the truth except through probes. The grammar tower is still a design until rebuilt and checked on the 0.5 core. A promotion study could compare one checked parser shown open versus closed. This page specifies a test, not a result.

<div class="ar-callout" markdown="1">
<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

The <a href="../../assets/data/worlds_v2/grammar.json">grammar@1 historical export</a> stores 58,669 layer-0 steps for the parse-count observation on eight operands separated by plus signs, with a successful outcome. That historical export uses machine notation, not a v3 display formula. Recompute costs from the kernel for every study input before reporting results; no ablation was run.
</div>

### Promotion ablation / pre-register

<section class="ar-card ar-study" markdown="1">

#### Study 01 / Parser promotion

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

- **Hypothesis:** a scoped promoted parser improves held-out parse/count success over the same parser shown unfolded.
- **Control:** the same grammar, inputs, agent, tools, and budget with an open boundary; compare exact layer-0 costs.
- **Failure criterion:** no matched-control gain, mismatched outcome or cost, scope violations, or a gain lost on held-out structures.
- **Limitation:** a shorter visible trace does not mean faster execution or transfer to new grammars.
- **Available today:** [grammar@1 design record](../assets/data/worlds_v2/grammar.json). No parser promotion study or model checkpoint.

</section>

<div class="ar-grid ar-grid-two" markdown="1">
<section class="ar-card" markdown="1">
<p class="ar-number">CONTROL / OPEN BOUNDARY</p>

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

Give the agent the same typed grammar, examples and tasks. Expand the parser at the chosen call boundary so each internal call is visible. Charge the exact layer-0 cost for the full unfolding. Supply the same context budget, tools, training records and test split as the promoted condition.

Visible trace length changes; full-state output and charged layer-0 steps must not.
</section>
<section class="ar-card" markdown="1">
<p class="ar-number">TREATMENT / CLOSED BOUNDARY</p>

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

Give the same agent a checked, promoted parser as one visible callable step with its hash, contract, and evidence scope attached. Do not use the promotion outside the checked scope. Unfold it for auditing and charge exactly the same layer-0 cost as in control.

A shorter displayed derivation is not a faster kernel evaluation.
</section>
</div>

**Primary outcome:** success on held-out, exactly scoped parse/count questions. **Secondary outcomes:** first wrong trace step, `Bottom` and `Unknown` rates, visible context tokens, and layer-0 cost per solved item. Compare plain and memoized recursion only when both versions record their exact layer-0 costs and identical outcomes. Seed and publish every split, model checkpoint, prompt, definition hash, boundary, and checker version.

### Five more proposed studies

The proposed to-frac bridge below has no implemented translation or checked commuting contract. The core can execute and verify bridges: [Learn / Checks](../learn/checks.md) shows a bounded to-difference check from the [kernel walkthrough](../assets/data/atoms2/walk.json). A transfer study still needs a versioned, scoped to-frac instance and trial.

<div class="ar-grid ar-grid-two" markdown="1">
<section class="ar-card ar-study" markdown="1">

#### Study 02 / Concept invention

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

- **Hypothesis:** checked novel definitions help on later tasks beyond a fixed library.
- **Control:** given-library-only and renamed-definition baselines on identical tasks.
- **Failure criterion:** no gain in valid novel definitions and held-out task reward.
- **Limitation:** a new name alone is not a new concept.
- **Available today:** [grammar@1 design record](../assets/data/worlds_v2/grammar.json); no invention trial or reward measurements.

</section>
<section class="ar-card ar-study" markdown="1">

#### Study 03 / Mechanistic interpretation

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

- **Hypothesis:** model states encode a trace's intermediate typed values.
- **Control:** shuffled-label probe, with definition hashes held out.
- **Failure criterion:** no out-of-split advantage over shuffled labels or no intervention effect.
- **Limitation:** decoding a value does not establish causal use.
- **Available today:** [grammar@1 design record](../assets/data/worlds_v2/grammar.json); no model states or probe results.

</section>
<section class="ar-card ar-study" markdown="1">

#### Study 04 / Autoformalization

<span class="ar-badge ar-badge-design" data-research-source="action">Designed example (action design record)</span>

- **Hypothesis:** a model can produce typed definitions and auditable outcome contracts from task text.
- **Control:** hand-authored specifications checked by the same independent checker.
- **Failure criterion:** invalid types, mismatched outcomes, or no improvement over control.
- **Limitation:** success on finite cases does not imply universal correctness.
- **Available today:** [action@2 design record](../assets/data/worlds_v2/action.json); no paired formalization results.

</section>
<section class="ar-card ar-study" markdown="1">

#### Study 05 / Model-side compilation

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

- **Hypothesis:** a compact intermediate representation improves deeper compositional tasks.
- **Control:** direct prompting, shuffled slot map, and unfolded representation.
- **Failure criterion:** no advantage on held-out depth with equal context and tools.
- **Limitation:** an execution smoke test does not establish model learning.
- **Available today:** [grammar@1 design record](../assets/data/worlds_v2/grammar.json); no compilation trial.

</section>
<section class="ar-card ar-study" markdown="1">

#### Study 06 / Cross-world transfer

<span class="ar-badge ar-badge-design" data-research-source="grammar">Designed example (grammar design record)</span>

- **Hypothesis:** a checked bridge preserves answers on held-out tasks across worlds.
- **Control:** matched within-world policy and an unbridged cross-world policy.
- **Failure criterion:** commuting check fails within scope or no held-out advantage.
- **Limitation:** one bounded bridge does not prove general transfer.
- **Available today:** [grammar@1 design record](../assets/data/worlds_v2/grammar.json) and a [bounded, executable bridge example](../assets/data/atoms2/walk.json) for to-difference; to-frac remains an unimplemented design, with no transfer trial.

</section>
</div>

These designs adapt ideas from the former operations-only experiment, environment, interpretation, and compilation guides. Those earlier **Legacy-v1** protocols and any old model scores do not constitute atoms-v2 measurements. [Specify visibility and split controls](protocols.md) before collecting data.

The archived Legacy-v1 model-internals experiment uses the optional `interp` extra. Its dependency marker is not an atoms-v2 study or a command to run one:

```text
# requires: opulse[interp]
```

<p class="ar-next" markdown="1">NEXT / [Build a world](../build/world.md) &nbsp; [Browse world designs](../worlds/index.md) &nbsp; [Review protocol controls](protocols.md)</p>

</div>
