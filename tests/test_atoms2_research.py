"""Research and Build pages keep their status and executable claims honest."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs/research/bundles/action-audit-v1"


def test_research_bundle_manifest_digests_and_real_sources():
    manifest = json.loads((BUNDLE / "MANIFEST.json").read_text(encoding="ascii"))
    assert set(manifest["files"]) == {path.name for path in BUNDLE.iterdir()} - {"MANIFEST.json"}
    for name, metadata in manifest["files"].items():
        content = (BUNDLE / name).read_bytes()
        assert metadata == {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    assert (BUNDLE / "action-export.json").read_bytes() == (ROOT / "docs/assets/data/worlds_v2/action.json").read_bytes()
    assert (BUNDLE / "action-declaration.json").read_bytes() == (ROOT / "worlds/decl/v2/action@2.json").read_bytes()
    declaration = json.loads((BUNDLE / "action-declaration.json").read_bytes())
    assert json.loads((BUNDLE / "action-lock.json").read_bytes()) == declaration["lock"]
    assert manifest["world_lock_hash"] == declaration["lock"]["world_hash"]
    assert manifest["scope"] == (
        "The bundle includes a seeded split of older `action@1` task IDs. "
        "It has no `action@2` maze episodes or evaluation results."
    )
    assert manifest["scope"] in (ROOT / "docs/research/protocols.md").read_text(encoding="utf-8")
    assert manifest["not_available"] and "scratchpad" not in json.dumps(manifest)
    assert "/tmp/" not in json.dumps(manifest)
    with zipfile.ZipFile(BUNDLE.with_suffix(".zip")) as archive:
        assert {name.removeprefix("action-audit-v1/") for name in archive.namelist()} == {path.name for path in BUNDLE.iterdir()}
        for path in BUNDLE.iterdir():
            assert archive.read("action-audit-v1/" + path.name) == path.read_bytes()


def test_research_bundle_split_is_seeded_family_disjoint_and_honest():
    from tools.research_bundle import split_tasks, task_index

    tasks = task_index()
    split = json.loads((BUNDLE / "split.json").read_text(encoding="ascii"))
    assert split == split_tasks(tasks)
    assert all(split["task_ids"].values())
    assert set().union(*(set(ids) for ids in split["task_ids"].values())) == {task["id"] for task in tasks}
    families = {task["id"]: task["family"] for task in tasks}
    groups = [{families[task_id] for task_id in ids} for ids in split["task_ids"].values()]
    assert all(not left & right for index, left in enumerate(groups) for right in groups[index + 1:])
    assert split_tasks(tasks, split["seed"] + 1) != split
    assert "not available" in split["compatibility"]


def test_research_bundle_check_detects_stale_and_missing_files(tmp_path, monkeypatch):
    import tools.research_bundle as bundle

    monkeypatch.setattr(bundle, "DEST", tmp_path)
    monkeypatch.setattr(bundle, "ARCHIVE", tmp_path.with_suffix(".zip"))
    monkeypatch.setattr("sys.argv", ["research_bundle.py"])
    assert bundle.main() == 0
    monkeypatch.setattr("sys.argv", ["research_bundle.py", "--check"])
    assert bundle.main() == 0
    (tmp_path / "metric.json").write_text("stale", encoding="ascii")
    assert bundle.main() == 1
    (tmp_path / "metric.json").unlink()
    assert bundle.main() == 1
    monkeypatch.setattr("sys.argv", ["research_bundle.py"])
    assert bundle.main() == 0
    tmp_path.with_suffix(".zip").write_bytes(b"stale")
    monkeypatch.setattr("sys.argv", ["research_bundle.py", "--check"])
    assert bundle.main() == 1


def test_research_study_cards_and_bundle_links():
    protocols = (ROOT / "docs/research/protocols.md").read_text(encoding="utf-8")
    experiments = (ROOT / "docs/research/experiments.md").read_text(encoding="utf-8")
    assert 'data-research-source="bundle"' in protocols
    assert "bundles/action-audit-v1.zip" in protocols
    assert 'data-research-manifest="../bundles/action-audit-v1/MANIFEST.json"' in protocols
    for name in ("MANIFEST", "action-export", "action-declaration", "action-lock", "task-index", "split", "metric"):
        assert f"bundles/action-audit-v1/{name}.json" in protocols
    for number in range(1, 7):
        card = experiments.split(f"Study {number:02d} /")[1].split("</section>")[0]
        for label in ("Hypothesis", "Control", "Failure criterion", "Limitation", "Available today"):
            assert f"**{label}:**" in card
    assert "/tmp/" not in protocols + experiments


def test_research_copy_separates_historical_exports_from_studies():
    research = (ROOT / "docs/research/index.md").read_text(encoding="utf-8")
    protocols = (ROOT / "docs/research/protocols.md").read_text(encoding="utf-8")
    experiments = (ROOT / "docs/research/experiments.md").read_text(encoding="utf-8")
    assert "A process reward model scores individual steps" in research
    assert "A study of conflict handling would need competing edits and an external test" in research
    assert "seeded split of older `action@1` task IDs" in protocols
    assert "no `action@2` maze episodes or evaluation results" in protocols
    assert "This page specifies a test, not a result" in experiments
    assert "Five more proposed studies" in experiments


def test_research_bundle_drawer_and_manifest_render_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = r"""
const {researchEvidence, renderManifest} = require(process.argv[1]);
const raw = require(process.argv[2]);
const record = researchEvidence('bundle', raw, '/research/bundles/action-audit-v1/MANIFEST.json');
global.document = {
  baseURI: 'https://example.test/research/protocols/',
  createElement(tag) {
    return {tag, children: [], appendChild(child) {this.children.push(child);},
      set textContent(text) {this.text = text;}};
  },
  createTextNode(text) {return {text};}
};
const panel = {dataset: {researchManifest: '../bundles/action-audit-v1/MANIFEST.json'},
  replaceChildren(...children) {this.children = children;}};
const page = {querySelector: () => panel};
renderManifest(page, url => {
  if (url.pathname !== '/research/bundles/action-audit-v1/MANIFEST.json') throw Error('wrong path');
  return Promise.resolve(raw);
}).then(() => console.log(JSON.stringify({record, count: panel.children[2].children.length,
  first: panel.children[2].children[0].children[0].href})));
"""
    result = subprocess.run([node, "-e", script, str(ROOT / "docs/assets/js/atoms2/research-ui.js"),
                             str(BUNDLE / "MANIFEST.json")], check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert output["record"]["artifact"]["schema"] == "opulse.research_bundle/1"
    assert "No action@2 episodes or evaluation run" in output["record"]["scope"]["description"]
    assert output["count"] == 6
    assert output["first"].startswith("https://example.test/research/bundles/action-audit-v1/")
PAGES = [ROOT / "docs" / folder / filename for folder, names in (
    ("research", ("index.md", "protocols.md", "experiments.md")),
    ("build", ("index.md", "world.md")),
) for filename in names]


def test_each_page_marks_designs_and_links_next_step():
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        assert "Designed example" in text or "Executable" in text, page
        assert 'class="ar-next"' in text, page
        assert "This page is being rebuilt" not in text, page


def test_new_pages_do_not_reintroduce_unicode_notation_or_long_dashes():
    forbidden = re.compile(r"[⟨⟩⟦⟧⦅⦆ℤℚ♠♦○◉◆◇■★▲♣⊙⁺⁻—–]")
    for page in PAGES:
        assert forbidden.search(page.read_text(encoding="utf-8")) is None, page


def test_legacy_research_pages_only_point_to_new_destinations():
    from tools.mkdocs_hooks import redirect_routes

    routes = redirect_routes()
    expected = {
        "why.md": "research/", "blog/index.md": "research/",
        "stitching/index.md": "research/experiments/", "experiments.md": "research/experiments/",
        "getting-started/concepts.md": "learn/kinds/",
        "getting-started/installation.md": "build/",
        "getting-started/notebooks.md": "reference/api/",
        "guide/benchmark.md": "research/protocols/",
        "guide/corpora.md": "research/protocols/",
        "guide/pretraining.md": "research/protocols/",
        "guide/integrations.md": "research/protocols/",
        "guide/export.md": "reference/api/",
        "guide/environments.md": "research/",
        "guide/interpretability.md": "research/experiments/",
        "guide/compiled-models.md": "research/experiments/",
        "guide/handwired.md": "research/experiments/",
        "guide/skeletons.md": "build/world/",
        "guide/discovery.md": "build/world/",
        "guide/generation.md": "build/world/",
        "guide/expressions.md": "build/world/",
        "guide/presets.md": "build/world/",
    }
    for name, destination in expected.items():
        source = Path(name)
        route = source.parent.as_posix() if source.name == "index.md" else source.with_suffix("").as_posix()
        assert not (ROOT / "docs" / source).exists(), name
        assert routes[route + "/"] == destination, name


def test_research_inline_render_preserves_code_and_skips_blocks():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = r"""
const {renderInline} = require(process.argv[1]);
function code(text, pre) {
  return {textContent: text, closest: query => query === 'pre' && pre ? {} : null,
    classList: {contains: () => false}, replaceWith(value) {this.rendered = value;}};
}
const expr = code('mul(17, 5)', false);
const token = code('?front_wall', false);
const block = code('PYTHONPATH=src python', true);
const items = [expr, token, block];
const page = {querySelectorAll: () => items};
const kit = {expr: text => ({kind:'expr', text}), token: text => ({kind:'token', text})};
console.log(JSON.stringify({count: renderInline(page, kit), result: items.map(x => x.rendered || null)}));
"""
    result = subprocess.run([node, "-e", script, str(ROOT / "docs/assets/js/atoms2/research-ui.js")],
                            check=True, capture_output=True, text=True)
    import json
    assert json.loads(result.stdout) == {"count": 2, "result": [
        {"kind": "expr", "text": "mul(17, 5)"},
        {"kind": "token", "text": "?front_wall"}, None,
    ]}


def test_quickstart_printed_output_matches_real_fixture():
    page = (ROOT / "docs/build/index.md").read_text(encoding="utf-8")
    from tools.mkdocs_hooks import current_core_digest, on_page_markdown

    published = on_page_markdown(
        page,
        SimpleNamespace(file=SimpleNamespace(src_uri="build/index.md")),
        SimpleNamespace(docs_dir=str(ROOT / "docs")),
        None,
    )
    command = re.search(r"```bash\n(PYTHONPATH=src python - <<'PY'\n.*?\nPY)\n```", page, re.DOTALL)
    output = re.search(r"Observed output in this checkout:\n\n```text\n(.*?)\n```", page, re.DOTALL)
    assert command and output
    assert "opulse.worlds_v2" not in command.group(1)
    assert f"Executable (core SHA-256 {current_core_digest()})" in published
    assert "Unknown(resource='fuel') layer-0 steps: 1" in output.group(1)
    assert "closed boundary: 1 visible calls; outcome: Ok(value=5) charged steps: 19" in output.group(1)
    assert "open boundary: 19 visible calls; outcome: Ok(value=5) charged steps: 19" in output.group(1)
    env = os.environ.copy()
    env["PATH"] = str(Path(os.sys.executable).parent) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(command.group(1), cwd=ROOT, env=env, shell=True,
                            capture_output=True, text=True, timeout=30, check=True)
    assert result.stdout.strip() == output.group(1)


def test_reference_distinguishes_core_checks_from_designed_examples():
    reference = (ROOT / "docs/reference/index.md").read_text(encoding="utf-8")
    api = (ROOT / "docs/reference/api.md").read_text(encoding="utf-8")
    glossary = (ROOT / "docs/reference/glossary.md").read_text(encoding="utf-8")
    for page in (reference, api, glossary):
        assert "not yet executable in the current core" not in page
        assert "not yet executable in this core" not in page
    assert "browser" in reference and "browser" in api
    assert "this table does not run those checks" in glossary
    for module in ("laws", "bridges"):
        assert f"src/opulse/atoms/{module}.py" in api
        assert f"opulse.atoms.{module}" in reference
    assert "replay_rewrite" in api
    assert "verify_bridge" in api


def test_provenance_ledger_describes_executable_mode_export():
    ledger = (ROOT / "docs/reference/provenance.md").read_text(encoding="utf-8")
    assert "[combination-mode panels](index.md#combination-modes)" in ledger
    assert "tools/atoms2_ui_export.py" in ledger
    assert "docs/assets/js/atoms2/data.js" in ledger
    assert "exact layer-0 steps" in ledger
    assert "not exhaustive or bounded verification" in ledger
    assert "Semantics sketches" not in ledger
