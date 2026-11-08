"""Synthetic open-kind exports stay out of the published index."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _node():
    """The Node.js binary: OPULSE_NODE, else node on PATH; skip when neither exists."""
    node = os.environ.get("OPULSE_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js not found: put node on PATH or set OPULSE_NODE")
    return node


KINDS = {
    "op_only": (["operation"], "open kinds: operation only"),
    "obj_only": (["object"], "open kinds: object only"),
    "comb_only": (["combinator"], "open kinds: combinator only"),
    "obs_only": (["observation"], "open kinds: observation only"),
    "obj_op": (["object", "operation"], "open kinds: object + operation"),
    "comb_obs": (["combinator", "observation"], "open kinds: combinator + observation"),
}


@pytest.fixture
def open_kind_exports(tmp_path: Path) -> Path:
    template = json.loads((ROOT / "docs/assets/data/worlds_v2/action.json").read_text())
    for world_id, (kinds, _) in KINDS.items():
        exported = dict(template, world=world_id, open_kinds=kinds)
        (tmp_path / f"{world_id}.json").write_text(json.dumps(exported))
    return tmp_path


def test_open_kinds_fixture_cards_filters_and_details(open_kind_exports: Path) -> None:
    script = r"""
      const fs = require('fs');
      const root = process.argv[1], fixtures = process.argv[2];
      class Element {
        constructor(tag) {
          this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.dataset = {};
          this.events = {}; this.className = ''; this._text = ''; this.parentElement = null;
          this.style = {setProperty() {}};
        }
        set textContent(value) { this._text = String(value); this.children = []; }
        get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
        setAttribute(key, value) { this.attrs[key] = value; }
        getAttribute(key) { return this.attrs[key]; }
        addEventListener(event, callback) { this.events[event] = callback; }
        appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
        append(...children) { children.forEach(child => this.appendChild(child)); }
        replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
        insertBefore(child, sibling) {
          child.parentElement = this;
          const at = this.children.indexOf(sibling);
          this.children.splice(at < 0 ? this.children.length : at, 0, child);
        }
        querySelectorAll(selector) {
          const results = [];
          const scan = node => node.children.forEach(child => {
            if (selector === child.tagName.toLowerCase()) results.push(child);
            scan(child);
          });
          scan(this);
          return results;
        }
        querySelector() { return null; }
        remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
      }
      const index = {schema: 'opulse.world_v2_index/1', worlds: process.argv[3].split(',').map(world =>
        ({world, file: world + '.json', title: world, wave: 1,
          open_kinds: ['object', 'operation', 'combinator', 'observation']}))};
      let mounts = [], ready, url = '';
      globalThis.document = {readyState: 'loading', addEventListener(_, callback) {ready = callback;},
        querySelectorAll(selector) { return selector.startsWith('[data-worlds-v2]') ? mounts.filter(node => !node.dataset.ready) : []; },
        createElement: tag => new Element(tag), createTextNode: text => {const node = new Element('#text'); node.textContent = text; return node;}};
      globalThis.location = {href: 'https://example.org/worlds/', pathname: '/worlds/', search: '', hash: ''};
      globalThis.history = {replaceState(_, __, value) {url = value;}};
      globalThis.fetch = async address => {
        const name = address.split('/').pop();
        const file = fs.existsSync(fixtures + '/' + name) ? fixtures + '/' + name :
          root + '/docs/' + address.replace(/^.*?(assets|worlds)\//, '$1/');
        return {ok: true, json: async () => name === 'index.json' ? index : JSON.parse(fs.readFileSync(file, 'utf8'))};
      };
      require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      require(root + '/docs/assets/js/worlds/catalog-ui.js');
      async function loaded(check) {
        for (let attempt = 0; attempt < 200; attempt++) {
          if (check()) return;
          await new Promise(resolve => setTimeout(resolve, 10));
        }
        throw Error('Page did not render');
      }
      async function run() {
        const catalog = new Element('div'); catalog.dataset.root = '../';
        const page = new Element('div'); page.appendChild(catalog); mounts = [catalog]; ready();
        await loaded(() => catalog.querySelectorAll('article').length >= 6);
        const cards = catalog.querySelectorAll('article').slice(0, 6).map(card => card.textContent);
        const select = page.querySelectorAll('select').find(item => item.attrs['aria-label'] === 'Open kinds');
        if (!select) throw Error('Visible open kinds filter missing');
        select.value = 'object'; select.events.change();
        const filtered = catalog.querySelectorAll('article').filter(card => card.className === 'w2-card');
        if (filtered.length !== 3 || !url.includes('open_kinds=object') ||
            !filtered.some(card => card.textContent.includes('obj_only')) ||
            !filtered.some(card => card.textContent.includes('obj_op')))
          throw Error('Open-kind filter failed: ' + filtered.length + ' / ' + url);
        const details = [];
        for (const entry of index.worlds) {
          const mount = new Element('div'); mount.dataset.root = '../../'; mount.dataset.world = entry.world;
          const detailPage = new Element('div'); detailPage.appendChild(mount); mounts = [mount]; ready();
          await loaded(() => mount.textContent.includes('Layer-0 givens'));
          details.push(mount.textContent);
        }
        console.log(JSON.stringify({cards, details}));
      }
      run().catch(error => {console.error(error); process.exitCode = 1;});
    """
    result = subprocess.run(
        [_node(), "-e", script, str(ROOT), str(open_kind_exports), ",".join(KINDS)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    for (world_id, (_, label)), card, detail in zip(KINDS.items(), rendered["cards"], rendered["details"]):
        assert world_id in card
        assert label in card
        assert label in detail


def test_all_four_kinds_and_optional_law_bridge_badges(open_kind_exports: Path) -> None:
    script = r"""
      const root = process.argv[1], fs = require('fs'), dir = process.argv[2];
      globalThis.document = {querySelectorAll: () => [], createElement: tag => ({tagName: tag, children: [], setAttribute() {},
        appendChild(child) {this.children.push(child)}, set textContent(text) {this.text = text}, get textContent() {return this.text}})};
      require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const ui = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const world = JSON.parse(fs.readFileSync(dir + '/op_only.json', 'utf8'));
      world.open_kinds = ['object', 'operation', 'combinator', 'observation'];
      const four = ui.openKindsBadge(world).textContent;
      world.open_kinds.push('law', 'bridge');
      console.log(JSON.stringify([four, ui.openKindsBadge(world).textContent]));
    """
    result = subprocess.run(
        [_node(), "-e", script, str(ROOT), str(open_kind_exports)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["open kinds: all four kinds", "open kinds: all four kinds + law + bridge"]


def test_published_open_kinds_worlds_match_their_declared_kinds() -> None:
    # The six open-kinds worlds are published by worlds; each export declares its open kinds.
    index = json.loads((ROOT / "docs/assets/data/worlds_v2/index.json").read_text())
    published = {entry["world"]: entry for entry in index["worlds"]}
    for world, (kinds, _badge) in KINDS.items():
        assert world in published, world
        export = json.loads((ROOT / "docs/assets/data/worlds_v2" / published[world]["file"]).read_text())
        declared = export.get("open_kinds") or export.get("decl", {}).get("open_kinds")
        assert sorted(declared) == sorted(kinds), (world, declared)
