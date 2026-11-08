import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def render_showcases(entries):
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}) => ({tag, text: attrs.text, attrs, children: [],
        appendChild(child) {this.children.push(child)}});
      A2.expr = value => A2.el('code', {text: value});
      A2.worlds = {ascii: value => String(value)};
      const {showcaseEntry, recordedAnswer, displayTitle} = require(process.argv[1] + '/docs/assets/js/worlds/catalog-ui.js');
      function lines(node) {return [node.text, ...node.children.flatMap(lines)].filter(value => value != null)}
      const entries = JSON.parse(process.argv[2]);
      console.log(JSON.stringify({shown: entries.map(entry => lines(showcaseEntry(entry, '/worlds/pixels.json'))),
        links: entries.map(entry => showcaseEntry(entry, '/worlds/pixels.json').children
          .flatMap(child => child.children || []).filter(child => child.tag === 'a').map(child => child.attrs.href)),
        fields: entries.map(entry => (recordedAnswer(entry) || {}).field || null),
        roads: displayTitle({world: 'roads', title: 'Road Closures and Cut Certificates'})}));
    """
    output = subprocess.run([NODE, "-e", script, str(ROOT), json.dumps(entries)],
                            check=True, text=True, capture_output=True)
    return json.loads(output.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_real_computer_showcases_display_recorded_answers_without_inventing_scope():
    entries = json.loads((ROOT / "docs/assets/data/worlds_v2/computer.json").read_text())["showcase"]
    result = render_showcases(entries)
    assert len(result["shown"]) == 3
    assert result["fields"] == ["answer"] * 3
    assert all("answer_checked: true" not in " ".join(lines) for lines in result["shown"])
    assert all("Answer recorded; check scope not recorded." in " ".join(lines)
               and "Answer check recorded" not in " ".join(lines)
               and json.dumps(entry["answer"], separators=(",", ":")) in " ".join(lines)
               for entry, lines in zip(entries, result["shown"]))
    assert "undefined" not in str(result)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_computer_checked_flag_without_answer_never_implies_a_displayed_check():
    entries = json.loads((ROOT / "docs/assets/data/worlds_v2/computer.json").read_text())["showcase"]
    for entry in entries:
        entry.pop("answer", None)
    result = render_showcases(entries)
    assert result["fields"] == [None] * 3
    for lines in result["shown"]:
        assert "The export marks answer_checked but stores no answer" in lines
        assert not any("Answer (" in line or "Historical export records answer_checked: true" in line
                       for line in lines)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_computer_answer_flag_with_scope_but_without_answer_has_no_check_badge():
    entries = [{"angle": "Compute", "prompt": "dot(x)", "answer_checked": True,
                "check_scope": "all bytes 0..255", "check_method": "bounded"}]
    result = render_showcases(entries)
    assert result["fields"] == [None]
    shown = " ".join(result["shown"][0])
    assert "The export marks answer_checked but stores no answer" in shown
    assert "Bounded" not in shown and "Executable" not in shown


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_pixels_showcase_answers_have_independent_historical_status_and_scope():
    entries = json.loads((ROOT / "docs/assets/data/worlds_v2/pixels.json").read_text())["showcase"]
    result = render_showcases(entries)
    assert len(result["shown"]) == len(entries)
    for entry, lines, links in zip(entries, result["shown"], result["links"]):
        shown = " ".join(lines)
        assert "Historical export" in shown
        assert entry["check_method"] in shown
        assert "scope not recorded" in shown
        assert "Designed example" not in shown
        assert links == ["/worlds/pixels.json"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_showcase_uses_recorded_scope_when_available():
    entry = {"angle": "Compute", "answer": "42", "answer_checked": True,
             "check_method": "independent reference", "check_scope": "inputs 0..9"}
    shown = " ".join(render_showcases([entry])["shown"][0])
    assert "Recorded scope: inputs 0..9." in shown
    assert "scope not recorded" not in shown


@pytest.mark.parametrize("entry,field", [
    ({"angle": "Compute", "prompt": "dot(x)", "answer_checked": True}, None),
    ({"angle": "Decide", "prompt": "?q{x}", "expected": False}, "expected"),
    ({"angle": "Compute", "result": 0}, "result"),
])
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_showcases_guard_missing_fields_and_preserve_false_and_zero(entry, field):
    result = render_showcases([entry])
    rendered = " ".join(result["shown"][0])
    assert result["fields"] == [field]
    assert "undefined" not in rendered and "answer_checked: true" not in rendered
    if field is None:
        assert "The export marks answer_checked but stores no answer" in rendered
    else:
        assert str(entry[field]).lower() in rendered


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tower_guards_missing_values():
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}) => ({tag, text: attrs.text});
      A2.expr = value => ({tag: 'code', text: value});
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      console.log(JSON.stringify({value: A2.worlds.safeValueNotation(),
        missing: A2.worlds.recordedValue('answer', undefined, []),
        zero: A2.worlds.recordedValue('answer', 0, [])}));
    """
    output = subprocess.run([NODE, "-e", script, str(ROOT)], check=True, text=True, capture_output=True)
    result = json.loads(output.stdout)
    assert result == {"value": "not recorded", "missing": {"tag": "p", "text": "No answer recorded"},
                      "zero": {"tag": "code", "text": "0"}}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_input_summaries_identify_differing_fields_without_missing_values():
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.register = () => {};
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const first = {ascii:'same(x)', inputs:[{t:'int', v:12}]};
      const second = {ascii:'same(x)', inputs:[{t:'int', v:14}]};
      const entry = {name:'test_step', examples:[first, second]};
      console.log(JSON.stringify({different:A2.worlds.caseInputSummary(entry, first),
        alone:A2.worlds.caseInputSummary({name:'test_step',examples:[first]}, first)}));
    """
    output = subprocess.run([NODE, "-e", script, str(ROOT)], check=True, text=True, capture_output=True)
    result = json.loads(output.stdout)
    assert result["different"].startswith("Recorded inputs[0].v:")
    assert result["alone"] is None
    assert "undefined" not in str(result)


def test_parse_status_available_for_world_declarations():
    status = json.loads((ROOT / "docs/assets/data/atoms2/parse_status.json").read_text())
    assert status["schema"] == "opulse.atoms2_parse_status/1"
    assert "computer/dot" in status["entries"]
    assert "roads/cut_certificate" in status["entries"]


def test_bridge_copy_distinguishes_core_support_from_unimplemented_design():
    pages = list((ROOT / "docs").rglob("*.md"))
    wrong_claim = re.compile(r"(?:law|bridge|~to_frac)[^.\n]*?(?:not yet executable|not a runnable definition|not executable in the current core)", re.IGNORECASE)
    assert not [str(page) for page in pages if wrong_claim.search(page.read_text())]
    experiments = (ROOT / "docs/research/experiments.md").read_text()
    assert "core can execute and verify bridges" in experiments
    assert "no implemented translation or checked commuting contract" in experiments
    walk = json.loads((ROOT / "docs/assets/data/atoms2/walk.json").read_text())
    assert walk["law_and_bridge"]["bridge"]["method"] == "bounded"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_roads_heading_and_host_computation_are_explicit():
    renderer = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    page = (ROOT / "docs/worlds/roads/index.md").read_text()
    assert "Road routes and a core-run cut" in page
    assert render_showcases([])["roads"] == "Road routes and a core-run cut"
    assert "cut observation has no rebuilt, checked 0.5 export" not in renderer
    assert "roads_core.json" in renderer


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_checked_answer_names_its_scope_or_says_the_scope_is_missing():
    base = {"angle": "Compute", "prompt": "dot(x)", "answer": "3", "answer_checked": True,
            "check_method": "bounded"}
    entries = [dict(base), dict(base, check_scope="all bytes 0..255"), dict(base, scope="unrecorded")]
    shown = [" ".join(lines) for lines in render_showcases(entries)["shown"]]
    assert "Answer recorded; check scope not recorded." in shown[0]
    assert "Answer check recorded" not in shown[0]
    assert "Answer check recorded." in shown[1] and "all bytes 0..255" in shown[1]
    assert "check scope not recorded" not in shown[1]
    assert "Answer recorded; check scope not recorded." in shown[2]
    assert "Answer check recorded" not in shown[2]
