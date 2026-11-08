"""World page coverage and URL-backed v2 filters."""

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


def test_exported_worlds_have_detail_pages() -> None:
    from mkdocs.config import load_config
    from mkdocs.structure.files import Files
    from tools.mkdocs_hooks import on_files

    config = load_config(str(ROOT / "mkdocs.yml"))
    config.plugins._current_plugin = None
    pages = on_files(Files([]), config)
    worlds = json.loads((ROOT / "docs/assets/data/worlds_v2/index.json").read_text())["worlds"]
    for item in worlds + [{"world": "computer"}]:
        source = ROOT / "docs/worlds" / item["world"] / "index.md"
        page = source.read_text() if source.exists() else next(
            entry.content_string for entry in pages if entry.src_uri == "worlds/" + item["world"] + "/index.md")
        assert 'data-world="' + item["world"] + '"' in page
        assert 'data-root="../../"' in page
        assert "worlds-v2.css" in page and "catalog-ui.js" in page


def test_legacy_worlds_are_separate_from_catalog() -> None:
    catalog = (ROOT / "docs/worlds/index.md").read_text()
    legacy = (ROOT / "docs/worlds/legacy.md").read_text()
    assert "data-opulse-worlds" not in catalog
    assert "docs/snippets/worlds/" not in catalog
    assert "Legacy-v1 worlds" in legacy
    assert "[See Legacy-v1 worlds](legacy.md)" in catalog
    assert "data-worlds-legacy" in legacy


def test_legacy_viewer_covers_the_twelve_published_artifacts() -> None:
    script = r"""
      const root = process.argv[1];
      const viewer = require(root + '/docs/assets/js/worlds/legacy-ui.js');
      console.log(JSON.stringify(viewer.ids));
    """
    result = subprocess.run([_node(), "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    ids = json.loads(result.stdout)
    assert len(ids) == 12
    assert all((ROOT / "docs/assets/data/worlds" / (item + ".json")).exists() for item in ids)
    for item in ids:
        world = json.loads((ROOT / "docs/assets/data/worlds" / (item + ".json")).read_text())
        names = {operator["name"] for operator in world["operators"]}
        assert set(world["curated"]) <= names
        assert all(atom["name"].isascii() for atom in world["atoms"])


def test_design_showcases_and_modalities_come_from_depth_records() -> None:
    design = json.loads((ROOT / "docs/worlds/designs.json").read_text())
    assert design["schema"] == "opulse.worlds_ui_design/1"
    assert len(design["worlds"]) == 21
    assert design["worlds"]["roads"]["answer"] == "Edges<AB,AC,AD>;true"
    assert len(design["worlds"]["roads"]["tower"]) == 12
    assert [entry["layer"] for entry in design["worlds"]["roads"]["tower"]] == list(range(1, 13))
    assert all("text" in item["modalities"] and item["prompt"] for item in design["worlds"].values())
    for item in design["worlds"].values():
        assert all(isinstance(item[key], str) and item[key].isascii() and item[key].strip()
                   for key in ("goal", "inputs", "output", "prompt"))
        assert item["goal"].endswith(".") and len(item["goal"].split()) < 25
        assert len(item["rules"]) >= 2 and all(rule.isascii() and rule.endswith(".") for rule in item["rules"])


def test_design_brief_shows_short_fields_and_preserves_full_prompt() -> None:
    script = r"""
      const root = process.argv[1];
      class Element {
        constructor(tag) { this.tagName = tag; this.children = []; this._text = ''; this.attrs = {}; }
        set textContent(value) { this._text = value; this.children = []; }
        get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
        setAttribute(key, value) { this.attrs[key] = value; }
        appendChild(child) { this.children.push(child); return child; }
      }
      globalThis.document = {querySelectorAll: () => [], createElement: tag => new Element(tag),
        createTextNode: value => { const node = new Element('#text'); node.textContent = value; return node; }};
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const design = require(root + '/docs/worlds/designs.json').worlds.integer;
      const brief = catalog.designBrief(design);
      const details = brief.children.find(child => child.tagName === 'details');
      console.log(JSON.stringify({text:brief.textContent, collapsed:details.tagName,
        prompt:details.textContent, rules:brief.children.find(child => child.tagName === 'ol').children.length}));
    """
    result = subprocess.run([_node(), "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert "Goal: Add four rational terms" in data["text"]
    assert "Inputs: List<qmul(" in data["text"]
    assert data["collapsed"] == "details"
    assert "Full design prompt" in data["prompt"]
    assert "CF<@fold_frac[qadd]" in data["prompt"]
    assert data["rules"] == 2


def test_new_world_pages_and_designs_use_ascii_only() -> None:
    pages = [ROOT / "docs/worlds/index.md", ROOT / "docs/worlds/legacy.md",
             ROOT / "docs/worlds/designs.json"]
    pages.extend((ROOT / "docs/worlds").glob("*/index.md"))
    pages.extend([ROOT / "docs/assets/js/worlds/catalog-ui.js",
                  ROOT / "docs/assets/js/worlds/legacy-ui.js",
                  ROOT / "docs/assets/js/atoms2/tower.js"])
    assert all(path.read_text().isascii() for path in pages)


def test_url_filters_use_exported_fields() -> None:
    script = r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const {filterWorlds, scope} = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const worlds = [
        {world:'action',title:'Robot',wave:1,story:[{kind:'observation',evidence:{},examples:[]}],tags:{domain:'agent',modalities:['text','image'],open_kinds:['observation']}},
        {schema:'opulse.world_v2_export/1',world:'grammar',title:'Grammar',wave:2,story:[{kind:'combinator',evidence:{checks:[1],world_hash:'abc',method:'bounded',scope:{size:1,checked:{size:1,sha256:'a'.repeat(64)}}},examples:[{trace:{},outcome:{ok:1},steps:1}]}]}
      ];
      console.log(JSON.stringify({wave:filterWorlds(worlds,{wave:'2'}).map(w=>w.world),
        kind:filterWorlds(worlds,{kind:'observation'}).map(w=>w.world),
        domain:filterWorlds(worlds,{domain:'agent'}).map(w=>w.world),
        modality:filterWorlds(worlds,{modalities:'image'}).map(w=>w.world),
        open:filterWorlds(worlds,{open_kinds:'observation'}).map(w=>w.world),
        status:filterWorlds(worlds,{status:'exported'}).map(w=>w.world),
        search:filterWorlds(worlds,{q:'robot'}).map(w=>w.world),
        ladders:Object.keys(scope).length, roads:scope.roads.length}));
    """
    result = subprocess.run([_node(), "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"wave": ["grammar"], "kind": ["action"],
                                         "domain": ["action"], "modality": ["action"], "open": ["action"],
                                         "status": ["grammar"], "search": ["action"],
                                         "ladders": 21, "roads": 5}


def test_catalog_pitches_are_unique_and_export_status_does_not_claim_execution() -> None:
    script = r"""
      const root = process.argv[1];
      require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const {pitch} = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const index = require(root + '/docs/assets/data/worlds_v2/index.json');
      console.log(JSON.stringify({pitch, worlds:index.worlds.map(item => item.world)}));
    """
    result = subprocess.run([_node(), "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert set(data["pitch"]) == set(data["worlds"]) | {"computer"}
    assert len(set(data["pitch"].values())) == len(data["pitch"])
    assert all(value.isascii() and value.endswith(".") for value in data["pitch"].values())
    viewer = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert 'A2.runBadge(card.example, coreUrl)' in viewer
    status = "Historical export"
    assert f'text: "{status}"' in viewer
    assert "Current core runs on this site:" in viewer
    for artifact in ("first_tower.json", "grammar_core.json", "roads_core.json"):
        assert f'path(mount, "assets/data/atoms2/{artifact}")' in viewer
    assert '"assets/data/worlds_v2/" + world.world + ".json"' in viewer
    assert 'row.appendChild(A2.badge(' not in viewer
    assert '"Separate from the executable export"' not in viewer
    assert 'text: "Historical export"' in viewer and '"scope not recorded", "w2-card-pending"' in viewer


@pytest.mark.parametrize("fixture_world", [False, True])
def test_catalog_and_roads_mount_without_dom_exceptions(fixture_world) -> None:
    script = r"""
      const fs = require('fs');
      const root = process.argv[1];
      const fixture = process.argv[2] === 'true';
      class Element {
        constructor(tag) {
          this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.dataset = {};
          this.events = {}; this.className = ''; this._text = ''; this.parentElement = null;
          this.style = {setProperty() {}};
        }
        set textContent(text) { this._text = String(text); this.children = []; }
        get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
        setAttribute(key, value) { this.attrs[key] = value; }
        addEventListener(event, callback) { this.events[event] = callback; }
        appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
        append(...children) { children.forEach(child => this.appendChild(child)); }
        replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
        insertBefore(child, sibling) {
          child.parentElement = this;
          const position = this.children.indexOf(sibling);
          this.children.splice(position < 0 ? this.children.length : position, 0, child);
        }
        querySelectorAll(selector) {
          const found = [];
          const scan = node => node.children.forEach(child => {
            if (selector === child.tagName.toLowerCase()) found.push(child);
            scan(child);
          });
          scan(this);
          return found;
        }
        querySelector() { return null; }
        focus() { document.activeElement = this; }
        click() { this.events.click(); }
        remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
      }
      const catalog = new Element('div'); catalog.dataset.root = '../';
      const catalogPage = new Element('div'); catalogPage.appendChild(catalog);
      const roads = new Element('div'); roads.dataset.root = '../../'; roads.dataset.world = 'roads';
      const roadsPage = new Element('div'); roadsPage.appendChild(roads);
      let mounts = [catalog];
      let ready;
      globalThis.document = {readyState:'loading', addEventListener(_, callback) {ready = callback;},
        querySelectorAll(selector) { return selector.startsWith('[data-worlds-v2]') ? mounts.filter(mount => !mount.dataset.ready) : []; },
        createElement: tag => new Element(tag), createTextNode: value => { const text = new Element('#text'); text.textContent = value; return text; }};
      globalThis.location = {href:'https://example.org/project/worlds/', search:'', pathname:'/project/worlds/', hash:''};
      let filteredURL = '';
      globalThis.history = {replaceState(_, __, url) { filteredURL = url; }};
      globalThis.fetch = async url => {
        const local = url.replace('https://example.org/project/', root + '/docs/');
        if (fixture && local.endsWith('/worlds_v2/index.json')) {
          const index = JSON.parse(fs.readFileSync(local, 'utf8'));
          index.worlds.push({world:'fixture_op_only',file:'fixture_op_only.json',title:'Fixture operation-only routes',wave:5});
          return {ok:true, json:async () => index};
        }
        if (fixture && local.endsWith('/worlds_v2/fixture_op_only.json')) {
          const exportWorld = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds_v2/roads.json', 'utf8'));
          exportWorld.world = 'fixture_op_only'; exportWorld.open_kinds = ['operation'];
          return {ok:true, json:async () => exportWorld};
        }
        return {ok: true, json: async () => JSON.parse(fs.readFileSync(local, 'utf8'))};
      };
      require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      require(root + '/docs/assets/js/worlds/catalog-ui.js');
      async function waitFor(check) {
        for (let attempt = 0; attempt < 100; attempt++) {
          if (check()) return;
          await new Promise(resolve => setTimeout(resolve, 10));
        }
        throw Error('World page did not mount: ' + catalogPage.textContent + ' / ' + roads.textContent);
      }
      async function run() {
        ready();
        await waitFor(() => catalogPage.querySelectorAll('select').length > 0);
        const firstCount = catalog.querySelectorAll('article').length;
        const worldCount = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds_v2/index.json', 'utf8')).worlds.length + 1;
        const more = catalog.querySelectorAll('button').find(button => button.className === 'w2-more');
        const total = worldCount + (fixture ? 1 : 0);
        const hasMore = more && more.textContent === 'Show all ' + total + ' worlds';
        more.click();
        const expandedCount = catalog.querySelectorAll('article').length;
        const openKindsLink = catalog.querySelectorAll('a').some(link => link.textContent === 'Explore world' &&
          link.attrs.href === 'https://example.org/project/worlds/op_only/');
        const fixtureLink = catalog.querySelectorAll('a').some(link => link.textContent === 'Explore world' &&
          link.attrs.href === 'https://example.org/project/worlds/fixture_op_only/');
        const wave = catalogPage.querySelectorAll('select').find(select => select.attrs['aria-label'] === 'Release group');
        const fixtureWave = wave.children.some(option => option.attrs.value === '5');
        const exact = catalogPage.querySelectorAll('select').find(select => select.attrs['aria-label'] === 'Exact open kinds');
        const fixtureSet = exact.children.some(option => option.attrs.value === 'operation' && option.textContent === 'operation only');
        if (fixture) {
          exact.value = 'operation'; exact.events.change();
          if (!catalog.querySelectorAll('a').some(link => link.attrs.href === 'https://example.org/project/worlds/fixture_op_only/'))
            throw Error('Exact operation-only filter lost the fixture world');
          exact.value = ''; exact.events.change();
        }
        wave.value = '3'; wave.events.change();
        const filteredCount = catalog.querySelectorAll('article').length;
        const catalogOK = firstCount === 9 && hasMore && expandedCount === total && openKindsLink &&
          (fixtureLink === fixture) && (fixtureWave === fixture) && fixtureSet &&
          filteredCount > 0 && filteredCount < expandedCount &&
          filteredURL.includes('wave=3') && catalogPage.textContent.includes('Current core runs on this site:') &&
          catalogPage.textContent.includes('have historical exports') &&
          catalog.querySelectorAll('a').some(link => link.textContent === 'Explore world' &&
            link.attrs.href === 'https://example.org/project/worlds/roads/') &&
          catalog.querySelectorAll('a').some(link =>
            link.textContent === 'Historical export' &&
            link.attrs.href.endsWith('.json'));
        const fromKindURL = new Element('div'); fromKindURL.dataset.root = '../';
        const kindPage = new Element('div'); kindPage.appendChild(fromKindURL);
        mounts = [fromKindURL];
        globalThis.location = {href:'https://example.org/project/worlds/?kind=law', search:'?kind=law',
          pathname:'/project/worlds/', hash:''};
        ready();
        await waitFor(() => kindPage.querySelectorAll('select').length > 0);
        const kindFilter = kindPage.querySelectorAll('select').find(select => select.attrs['aria-label'] === 'Tower or open kind');
        const advanced = kindPage.querySelectorAll('details').find(details => details.className === 'w2-advanced');
        const filteredByKind = fromKindURL.querySelectorAll('article').length;
        const selectedFromURL = kindFilter && kindFilter.value === 'law' && advanced.open &&
          filteredURL.includes('kind=law') && filteredByKind < firstCount;
        kindFilter.value = '';
        kindFilter.events.change();
        const kindQuery = selectedFromURL && !filteredURL.includes('kind=') &&
          fromKindURL.querySelectorAll('article').length === firstCount &&
          kindPage.querySelectorAll('select').some(select => select.attrs['aria-label'] === 'Open kinds') &&
          kindPage.querySelectorAll('select').some(select => select.attrs['aria-label'] === 'Exact open kinds');
        mounts = [roads];
        globalThis.location = {href:'https://example.org/project/worlds/roads/', search:'', pathname:'/project/worlds/roads/', hash:''};
        ready();
        await waitFor(() => roads.textContent.includes('Twelve-layer design record'));
        const text = roads.textContent;
        const rail = roads.querySelectorAll('div').find(element => element.attrs['aria-label'] === 'Select a designed layer');
        if (!rail) throw Error('Designed tower control missing');
        const buttons = rail.querySelectorAll('button');
        const initial = roads.textContent.includes('DESIGN LAYER 12');
        buttons[0].click();
        const selected = roads.textContent.includes('DESIGN LAYER 1');
        buttons[0].focus();
        rail.events.keydown({key:'ArrowRight',preventDefault() {}});
        const keyboard = roads.textContent.includes('DESIGN LAYER 2') && document.activeElement === buttons[1];
        console.log(JSON.stringify({catalogOK, kindQuery, loaded:text.includes('CURRENT CORE / METRO RUNS'),
          design:text.includes('Twelve-layer design record'), witness:text.includes('Edges<AB,AC,AD>'),
              buttons:buttons.length, badge:text.includes('Designed example') &&
                text.includes('Bounded: all 256 weightings of one 4-node topology'),
          contract:text.includes('Layer-0 givens'), initial, selected, keyboard}));
      }
      run().catch(error => { console.error(error); process.exitCode = 1; });
    """
    result = subprocess.run([_node(), "-e", script, str(ROOT), str(fixture_world).lower()],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"catalogOK": True, "kindQuery": True, "loaded": True, "design": True,
                                         "witness": True, "buttons": 12, "badge": True,
                                         "contract": True, "initial": True,
                                         "selected": True, "keyboard": True}
