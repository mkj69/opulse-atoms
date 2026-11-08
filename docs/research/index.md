# Research uses

<link rel="stylesheet" href="../assets/css/atoms2-research.css">
<script defer src="../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

<p class="ar-kicker">RESEARCH / 01 &nbsp; USE CASES</p>

## Finite traces need external tests

A finite world fixes its operations, permitted observations, and judge view. Opulse records definitions, outcomes, and layer-0 costs under that contract. A trace shows what happened inside that world; it does not show that a model improves on external tasks. The `versions` design below asks what a merge trace could be used to measure, not what it already proves.

<div class="ar-callout" markdown="1">
<span class="ar-badge ar-badge-design" data-research-source="versions">Designed example (versions design record)</span>

The [`versions@1` design record](../assets/data/worlds_v2/versions.json) specifies two paths, three possible texts, an immutable parent ledger and a conflict value. Its stored outcome is a historical export, not a model or policy evaluation.
</div>

### One artifact, three questions

<div class="ar-grid" markdown="1">
<section class="ar-card" markdown="1">
<p class="ar-number">01 / FINITE RL</p>

#### Can an agent learn to resolve a conflict?

<span class="ar-badge ar-badge-design" data-research-source="versions">Designed example (versions design record)</span>

**State:** a base version, two edited descendants, and the visible conflict record. **Action:** choose a permitted merge or resolution operation. **Reward:** a task-specific score for the resulting version, computed by a full-state judge. State and action are typed; a high task reward alone does not certify that a definition unfolds equivalently.

Compare a policy using only granted probes with one that sees the entire parent ledger. That comparison is a leakage audit, not a fair baseline for the restricted policy.
</section>
<section class="ar-card" markdown="1">
<p class="ar-number">02 / PROCESS LABELS</p>

#### Where did a derivation fail?

<span class="ar-badge ar-badge-design" data-research-source="versions">Designed example (versions design record)</span>

Each attempted step needs an outcome, a scope and a reason. A process reward model scores individual steps. Candidate labels are `Ok(value)`, `Bottom(reason)` and `Unknown(resource)`; no model was trained on this export. A merge conflict can be an `Ok` value; do not recast it as `Bottom`. `Unknown(fuel)` means evaluation ran out of budget and **never counts as correct**.

</section>
<section class="ar-card" markdown="1">
<p class="ar-number">03 / DIAGNOSTIC PAIRS</p>

#### Same answer, different path?

<span class="ar-badge ar-badge-design" data-research-source="versions">Designed example (versions design record)</span>

Pair runs that end in the same projected task answer but differ in provenance, conflict handling, trace, or exact layer-0 cost. Keep both complete records. A model that predicts the same final answer for both may still make different process errors; inspect the divergence before treating either run as valid.

</section>
</div>

### Trace to use

<div class="ar-callout" markdown="1">
<span class="ar-badge ar-badge-design" data-research-source="versions">Designed example (versions design record)</span>

The [historical export](../assets/data/worlds_v2/versions.json) records an `apply` operation that changes two independent document paths in one state change, with 119 layer-0 steps and an `Ok` outcome. Its displayed call is not runnable parser source, so it is not reproduced here. A study of conflict handling would need competing edits and an external test.
</div>

<div class="ar-flow" role="img" aria-label="A versioned world declaration and typed trace feed three proposed analyses: finite policy reward, per-step process labels, and paired process diagnostics. A separate external evaluation is still missing.">
  <span>World + scope<br><small>version, probes, judge view</small></span>
  <span>Typed trace<br><small>outcome, cost, full state</small></span>
  <span>Research question<br><small>policy / PRM / paired records</small></span>
  <span>External test missing<br><small>real tasks, people, transfer</small></span>
</div>

### What is not established

The legacy operation-only experiments motivate these designs, but their metrics are not atoms-v2 results. A study still needs independent ground truth, pinned splits, matched baselines, uncertainty across seeds, and held-out environments. No current artifact here measures improvement in human decision-making, general model reasoning, or transfer to real version-control systems. [Write a protocol](protocols.md) before claiming any of those outcomes.

<p class="ar-next" markdown="1">NEXT / [Specify the protocol](protocols.md) &nbsp; [Inspect study designs](experiments.md) &nbsp; [Browse worlds](../worlds/index.md)</p>

</div>
