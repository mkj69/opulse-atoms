"""Shared step viewer wiring and a few trace highlighting edge cases."""

import shutil
import subprocess
from pathlib import Path

import pytest
from ui_ascii_mirror import assert_ascii_legacy_mirror

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "docs/assets/js"


def test_registered_before_widgets_and_shared_style():
    config = (ROOT / "mkdocs.yml").read_text()
    # The step viewer is loaded only by the page that uses it, before the widget script.
    assert "  - assets/js/stepview.js" not in config
    assert "  - assets/js/playground.js" not in config
    assert "  - assets/css/playground.css" not in config
    legacy_page = (ROOT / "docs/play/legacy.md").read_text()
    assert '<script src="../../assets/js/playground.js"></script>' in legacy_page
    assert legacy_page.index('<script src="../../assets/js/stepview.js"></script>') < legacy_page.index(
        '<script src="../../assets/js/playground.js"></script>')
    assert '<link rel="stylesheet" href="../../assets/css/stepview.css">' in legacy_page
    assert '<link rel="stylesheet" href="../../assets/css/playground.css">' in legacy_page
    source = (JS / "stepview.js").read_text()
    for marker in ("function render(container, options)", "page_size", "options.initial", "options.labels",
                   "options.renderValue", "source.load(offset, size)", "aria-activedescendant",
                   "prefers-reduced-motion", "goToStep(n)", "ArrowDown", "PageDown"):
        assert marker in source
    style = (ROOT / "docs/assets/css/stepview.css").read_text()
    for marker in (".opg-detail", ".opg-steps", ".opg-focus", ".opg-new", "max-width: 44.9375em"):
        assert marker in style


def test_every_derivation_widget_uses_shared_viewer():
    wiring = {
        "playground.js": ("OpulseStepView.render", "steps, initial:", "explain(out.steps[index], state.atomRules)"),
        "scales-core.js": ("OpulseStepView.render", "example.page(cut, offset, size)", "example.count(cut)"),
        "scales-tour.js": ("api.renderStepList(stepBox", "OpulseStepView.render", "current.statuses"),
        "home-scales.js": ("api.renderStepList(listBox", "api.renderTree(treeBox"),
        "challenge.js": ("OpulseStepView.render", "example.fullPage(offset, size)", "coarse_steps"),
        "challenge-modes.js": ("OpulseStepView.render", "item.correct_steps", 'mode === "hole"'),
    }
    for filename, markers in wiring.items():
        source = (JS / filename).read_text()
        assert all(marker in source for marker in markers), filename
    assert "i ? lines[i - 1] : data.question" in (JS / "scales-tour.js").read_text()
    assert "rows[0].before !== undefined" in (JS / "challenge-modes.js").read_text()
    assert not (ROOT / "docs/guide/visual-tour.md").exists()
    if (ROOT / "docs_zh").is_dir():
        assert "vis_unfold_scales.html" not in (ROOT / "docs_zh/guide/visual-tour.md").read_text()


def test_chinese_localized_overrides_match():
    if not (ROOT / "docs_zh").is_dir():
        pytest.skip("The public export has no Chinese site")
    for filename in ("playground.js", "scales-tour.js", "challenge.js"):
        assert_ascii_legacy_mirror(JS / filename, ROOT / "docs_zh/snippets/localized_assets/js" / filename)


@pytest.mark.parametrize("filename", [
    "stepview.js", "playground.js", "scales-core.js", "scales-tour.js", "home-scales.js",
    "challenge.js", "challenge-modes.js",
])
def test_javascript_syntax(filename):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    subprocess.run([node, "--check", str(JS / filename)], check=True, capture_output=True)


def test_diff_spans_share_context_without_highlighting_unchanged_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    script = """const vm=require('node:vm'),fs=require('node:fs');
const context={window:{}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const diff=context.window.OpulseStepView.difference;
const cases=[['a + b','a * b',[[2,3],[2,3]]],['(2 + 2) * 3','4 * 3',[[0,7],[0,1]]],['abc','abc',[[3,3],[3,3]]]];
for(const [a,b,expected] of cases){const got=diff(a,b);if(JSON.stringify(got)!==JSON.stringify(expected))throw Error(JSON.stringify({a,b,got,expected}));}
"""
    subprocess.run([node, "-e", script, str(JS / "stepview.js")], check=True, capture_output=True)


def test_lazy_page_navigation_and_highlights():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    subprocess.run([node, str(ROOT / "tests/js/stepview-smoke.js"), str(JS / "stepview.js")],
                   check=True, capture_output=True)


def test_operation_identity_and_invariant_pure_functions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    script = """const vm=require('node:vm'),fs=require('node:fs');
const context={window:{}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const api=context.window.OpulseStepView;
const given=api.operationIdentity({operator_kind:'atom',atom:'add',symbol:'+'});
if(given.kind!=='operation'||given.origin!=='given'||given.layer!==0||given.name!=='add')throw Error('given chip');
for(const [type,node] of [['simple','call'],['branch','case'],['recursive','rec']]){
  const def=api.operationIdentity({operator_kind:type,symbol:'◆'});
  if(def.origin!=='invented'||def.node!==node)throw Error(type);
}
if(api.operationIdentity({kind:'undefined'})!==null)throw Error('undefined should have no chip');
const items=api.invariantItems({result:0,charged:2,shown:3},{result:'Result',charged:'Charged',shown:'Shown'});
if(JSON.stringify(items.map(item=>item.value))!=='["0","2","3"]')throw Error('invariant');
"""
    subprocess.run([node, "-e", script, str(JS / "stepview.js")], check=True, capture_output=True)
