"""Real-export checks for the world detail showcase and sealed results."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_node(script):
    output = subprocess.run([NODE, "-e", script, str(ROOT)], capture_output=True,
                            text=True, check=True)
    return json.loads(output.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_each_world_export_renders_every_published_showcase_and_answer():
    result = run_node(r"""
      const fs = require('fs');
      const base = process.argv[1];
      const A2 = require(base + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, text: attrs.text, children,
        appendChild(child) {this.children.push(child)}});
      A2.expr = text => A2.el('code', {text});
      A2.worlds = {ascii: text => String(text)};
      const {publishedShowcases} = require(base + '/docs/assets/js/worlds/catalog-ui.js');
      function strings(element) {
        return [element.text, ...(element.children || []).flatMap(strings)].filter(value => value != null);
      }
      const worlds = fs.readdirSync(base + '/docs/assets/data/worlds_v2')
        .filter(name => name.endsWith('.json') && name !== 'index.json').map(name => {
          const world = require(base + '/docs/assets/data/worlds_v2/' + name);
          const card = A2.el('section');
          const count = publishedShowcases(card, world, '/worlds/' + name);
          const entries = (world.showcase || []).map((entry, index) => {
            const shown = strings(card.children[index]).join(' ');
            return {prompt: shown.includes(entry.prompt), answer: shown.includes(
              typeof entry.answer === 'string' ? entry.answer : JSON.stringify(entry.answer)),
              checked: entry.answer_checked === true ? ((entry.check_scope || entry.scope) &&
                (entry.check_scope || entry.scope) !== 'unrecorded' ? shown.includes('Answer check recorded.') :
                shown.includes('Answer recorded; check scope not recorded.') &&
                !shown.includes('Answer check recorded')) :
                shown.includes('No answer check recorded.'),
              scope: shown.includes('scope not recorded'),
              noUnscopedBadge: !/Exhaustively checked|Bounded \(|Seeded sample/.test(shown)};
          });
          return {name, count, length: (world.showcase || []).length, entries};
        });
      console.log(JSON.stringify(worlds));
    """)
    assert len(result) >= 21
    assert all(world["count"] == world["length"] >= 3 for world in result)
    assert all(all(entry.values()) for world in result for entry in world["entries"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_empty_showcase_only_for_exports_without_questions():
    result = run_node(r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}) => ({tag, attrs, children: [], appendChild(child) {this.children.push(child)}});
      A2.expr = value => A2.el('code', {text: value});
      A2.worlds = {ascii: value => String(value)};
      const {publishedShowcases} = require(process.argv[1] + '/docs/assets/js/worlds/catalog-ui.js');
      const card = A2.el('section');
      console.log(JSON.stringify({absent: publishedShowcases(card, {}, '/worlds/empty.json'),
        empty: publishedShowcases(card, {showcase: []}, '/worlds/empty.json'), children: card.children.length}));
    """)
    assert result == {"absent": 0, "empty": 0, "children": 0}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_action_sealed_results_hide_marker_in_tower_and_traces():
    result = run_node(r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const action = require(process.argv[1] + '/docs/assets/data/worlds_v2/action.json');
      const examples = action.story.flatMap(row => row.examples || []).filter(example =>
        example.outcome && example.outcome.ok && example.outcome.ok.sealed_fixture);
      console.log(JSON.stringify({length: examples.length,
        shown: examples.map(example => A2.worlds.outcomeNotation(example.outcome)),
        trace: examples.map(example => A2.worlds.traceLines(example.trace, [], 0, example.text))}));
    """)
    assert result["length"] >= 2
    assert set(result["shown"]) == {"sealed (judge-only)"}
    assert '"sealed_fixture"' not in json.dumps(result["trace"])
    assert any(step["outcome"] == "sealed (judge-only)"
               for trace in result["trace"] for step in trace)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_nested_redaction_markers_are_sealed_but_normal_outcomes_remain_visible():
    result = run_node(r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      console.log(JSON.stringify({nested: A2.worlds.outcomeNotation({ok:{v:[{judge_only:true}]}}),
        redacted: A2.worlds.outcomeNotation({ok:{redaction_marker:'private'}}),
        normal: A2.worlds.outcomeNotation({ok:{t:'int',v:21}})}));
    """)
    assert result == {"nested": "sealed (judge-only)", "redacted": "sealed (judge-only)",
                      "normal": "Ok(21)"}
