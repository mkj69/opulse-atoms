# Provenance

<link rel="stylesheet" href="../../assets/css/atoms2-research.css">
<script defer src="../../assets/js/atoms2/research-ui.js"></script>

<div class="ar-page" markdown="1">

Behavioral claims need a versioned artifact, a declared check scope and a reproducible method. Design material is not a check. A projected reward does not prove full-state equivalence. See [semantics](index.md) and [research protocols](../research/protocols.md).

## Claim ledger

<span class="ar-badge ar-badge-executable">Executable</span>

`src/opulse/atoms/kernel.py` and `src/opulse/atoms/values.py` implement `Ok`, `Bottom`, `Unknown` and finite limits under `{{ A2_SPEC_VERSION }}` (`docs/spec/atoms-v2.md` in the repository). Core input SHA-256: `{{ A2_CORE_DIGEST }}` (first 12 hex digits of the digest of sorted core Python file paths and bytes). This is an implementation claim, not an exhaustive check. A code or contract change needs a new test and claim.

<span class="ar-badge ar-badge-design">Designed example</span>

[`shadows.json`](../assets/data/worlds_v2/shadows.json) carries schema `opulse.world_v2_export/1`, a world version and declaration lock. It does not independently check the glossary's two-body example. A world edit needs a new lock and evidence.

<span class="ar-badge ar-badge-design">Designed example</span>

**Auditable design file, not a checked claim:** the [published `action.json` export](../assets/data/worlds_v2/action.json) has SHA-256 file digest `{{ A2_ACTION_EXPORT_SHA256 }}`. The export stores declaration lock value `{{ A2_ACTION_LOCK_WORLD_HASH }}`. The stored value matches the declaration hash computed by `WorldDecl.world_hash()` in this checkout, but neither hash certifies a checker result. The file digest covers the bytes served by the built site, not the unbuilt source file. The [downloadable audit template](../research/action-audit-v1.json) copies the stored lock value and records a proposed method, but its checker revision, seeds, results and changed-claim comparison are `null`. The executable examples above have versioned run artifacts. This ledger does not yet include an independently checked world-example claim binding a completed checker result to a published file hash. A changed export needs a new digest and a new check.

<span class="ar-badge ar-badge-executable">Executable</span>

The [combination-mode panels](index.md#combination-modes) replay kernel runs exported by `tools/atoms2_ui_export.py` into `docs/assets/js/atoms2/data.js`. Each panel shows its recorded input, outcome, exact layer-0 steps and core SHA-256; the memo panel also distinguishes charged steps from executed work. These are executable input traces, not exhaustive or bounded verification of the general modes. The export does not provide a checker scope or verified world hash for those broader claims. The panel's core SHA-256 identifies the exported run, which may differ from this page's build-time core SHA-256.

<span class="ar-badge">Legacy-v1</span>

Historical benchmarks are in repository history, not atoms-v2 throughput evidence. A v2 benchmark needs hardware, seed, code version, inputs and repeat.

A verification record should contain a definition content hash, world hash and version, method, scope, seed if sampled, layer-0 cost, judge view, outcome and checker artifact. Bounded evidence covers only its stated bound. A seeded sample can be stored but cannot license promotion. Editing a definition or its dependencies gives a new identity and detaches old evidence; promotion never survives an edit silently.

## Lineage and versions

The earlier published site taught operator-only worlds. This published interface is now `legacy-v1`. The atoms-v2 design covers six definable kinds, templates and meta definitions. The <a href="../spec/">versioned core specification</a> describes an implemented subset; do not treat older operator-only results as evidence for the extensions. Historical v1 release notes remain in repository history under `docs/about/changelog.md`.

## Cite and contribute

Repository-root `CITATION.cff` contains software citation metadata. Cite the specific code revision and data used in a study. `LICENSE` covers code (Apache-2.0); `LICENSE-docs` covers docs and data (CC BY 4.0); `LICENSES` records bundled third-party terms. Repository-root `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` give the contribution process. A useful issue includes a minimal world/input, dialect, version, seed, expected full-state outcome, actual outcome and reproducible command. Do not present an unverified design sketch as a passed test.

[Next: Research protocols](../research/protocols.md) | [Browse worlds](../worlds/index.md)

</div>
