"""Chip shape, copy-visible text, and world object-name regressions."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
SHARED_CSS = (ROOT / "docs/assets/css/atoms2.css").read_text()
LEARN_CSS = (ROOT / "docs/assets/css/learn.css").read_text()


def css_rule(css: str, selector: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    rules = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in match.group(1).strip().split(", ") or selector == match.group(1).strip():
            rules.append(match.group(2))
    assert rules, selector
    return rules[-1]


def test_button_chip_keeps_law_double_bar_over_generic_button_border() -> None:
    law = css_rule(SHARED_CSS, ".a2-chip.a2-k-law")
    law_token = css_rule(SHARED_CSS, ".a2-tok.a2-k-law")
    button = css_rule(SHARED_CSS, ".a2-learn-app button.a2-tok")
    generic_button = css_rule(LEARN_CSS, ".a2-learn-app button")
    assert "border: 1px solid" in generic_button
    assert ".a2-tok.a2-k-law".count(".") > ".a2-learn-app button".count(".")
    assert "border-style: double" in law
    assert "border-width: 3px" in law
    assert "border-radius: 2px" in law
    assert "border-top-width: 4px" in law_token
    assert "border-bottom-width: 4px" in law_token
    assert "border-color: var(--a2-k)" in button
    assert not re.search(r"(?:^|;)\s*border\s*:", button)
    assert not re.search(r"(?:^|;)\s*border-(?:style|width|radius)\s*:", button)
    assert ".a2-learn-app button" in LEARN_CSS


def test_copyable_tokens_and_chips_wrap_without_ellipsis() -> None:
    token = css_rule(LEARN_CSS, ".a2-learn-app .a2-tok")
    chip_name = css_rule(SHARED_CSS, ".a2-chip-name")
    shared_token = css_rule(SHARED_CSS, ".a2-tok")
    for style in (token, chip_name, shared_token):
        assert "overflow-wrap: anywhere" in style
        assert "ellipsis" not in style
        assert "white-space: nowrap" not in style
    assert "white-space: normal" in token
    assert "max-width: 100%" in shared_token
    assert "overflow: hidden" not in token


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_integer_object_labels_use_declared_names_but_keep_record_ids() -> None:
    script = """
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const integer = require(process.argv[1] + '/docs/assets/data/worlds_v2/integer.json');
      const story = integer.story.filter(row => row.kind === 'object');
      const fallback = {kind:'object', name:'hour'};
      const declared = {kind:'object', name:'hour', ascii:'obj Hour = Quot[Int, mod12] L1'};
      console.log(JSON.stringify({labels:story.map(A2.worlds.displayIdentifier),
        ids:story.map(A2.worlds.identifier), fallback:A2.worlds.displayIdentifier(fallback),
        declared:A2.worlds.displayIdentifier(declared),
        unchanged:A2.worlds.displayIdentifier({kind:'law', name:'assoc_count'})}));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {
        "labels": ["Nat", "Frac", "CF", "QuotFrac", "Hour"],
        "ids": ["nat", "frac", "cf", "quot_frac", "hour"],
        "fallback": "Hour", "declared": "Hour", "unchanged": "#assoc_count",
    }
    tower = (ROOT / "docs/assets/js/atoms2/tower.js").read_text()
    catalog = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    # Notation v3: chips look up the stored name in the legend and fall back to the declared
    # display identifier only when no mark exists.
    assert "entry.name : displayIdentifier(entry)" in tower and "A2.token(chipText(entry, world)" in tower
    assert "A2.worlds.displayIdentifier(entry)" in catalog
    assert "A2.worlds.displayIdentifier(Object.assign({ kind: kind }, item))" in catalog
