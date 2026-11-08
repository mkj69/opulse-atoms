"""World export and legacy display regressions."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_js(script):
    if not NODE:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", script, str(ROOT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_design_declaration_and_example_are_labeled_and_never_sent_as_formulas():
    result = run_js(r"""
      const root = process.argv[1];
      const N3 = require(root + '/docs/assets/js/atoms2/n3.js');
      const declaration = 'op planned(x) = <future> L1';
      const example = 'planned(↝future)';
      N3.register({worlds: {designworld: {legend: [{name:'planned',kind:'operation'}],
        designs: [declaration, example], formulas: {}}}});
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children: [], appendChild(child) {this.children.push(child)}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      Object.assign(A2, {el, token: text => el('token', {text}),
        expr: (text, opts) => el('code', {text, class: opts.design || N3.isDesign(text, opts.world) ? 'a2-design-text' : 'a2-expr', design:opts.design}),
        value: (value) => el('value', {value})});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const entry = {name:'planned',kind:'operation',design_decl:declaration,
        examples:[{text:example, outcome:{ok:3}}]};
      const card = A2.worlds.entryCard(entry, [entry], '', {}, 'designworld');
      const flatten = node => [node, ...(node.children || []).flatMap(flatten)];
      console.log(JSON.stringify(flatten(card).filter(node =>
        node.attrs.text === declaration || node.attrs.text === example ||
        /Design text \(not notation v3/.test(node.attrs.text || '')).map(node => node.attrs)));
    """)
    assert {"text": "op planned(x) = <future> L1", "class": "a2-design-text", "design": True} in result
    assert any(node.get("text") == "Design text (not notation v3 source)" for node in result)
    assert any(node.get("text") == "Design text (not notation v3)" for node in result)
    assert any(node.get("text") == "planned(↝future)" and node.get("class") == "a2-design-text"
               for node in result)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_world_design_and_legacy_badges_open_source_records():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.badge = (status, options) => ({status, record: options.record});
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const legacy = require(root + '/docs/assets/js/worlds/legacy-ui.js');
      console.log(JSON.stringify({
        design: catalog.designBadge('roads', 'Difficulty level 1', '../../worlds/designs.json'),
        legacy: legacy.legacyBadge({world:'action'}, 'Given operation move')
      }));
    """)
    assert result["design"] == {
        "status": "design", "record": {
            "method": "not run", "scope": {"domain": "roads", "description":
                "Difficulty level 1. Proposed in the depth design; no verification run is recorded."},
            "artifact": {"file": "Design record: roads world, depth pass (11-04)",
                         "href": "../../worlds/designs.json", "schema": "opulse.worlds_ui_design/1"},
        },
    }
    assert result["legacy"]["status"] == "legacy"
    assert result["legacy"]["record"]["artifact"]["href"] == "../../assets/data/worlds/action.json"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_duplicate_calls_show_distinguishing_bot_state_and_generic_input():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const story = require(root + '/docs/assets/data/worlds_v2/action.json').story;
      const step = story.find(entry => entry.name === 'safe_step');
      const summary = step.examples.map(example => A2.worlds.caseInputSummary(step, example));
      const sameCall = {name:'move', examples:[
        {ascii:'move(x)', inputs:[{t:'int',v:12}]},
        {ascii:'move(x)', inputs:[{t:'int',v:23}]}
      ]};
      console.log(JSON.stringify({summary, generic:sameCall.examples.map(example =>
        A2.worlds.caseInputSummary(sameCall, example))}));
    """)
    assert result["summary"] == [
        "Bot: position (1, 1), facing E, maze M2",
        "Bot: position (1, 1), facing N, maze M1",
    ]
    assert result["generic"] == ["Recorded inputs[0].v: 12", "Recorded inputs[0].v: 23"]
    script = (ROOT / "docs/assets/js/atoms2/tower.js").read_text()
    assert 'callLine.appendChild(text("span", inputSummary' in script
    assert 'inputLine.appendChild(text("span", "Inputs:"' in script
    assert 'inputLine.appendChild(A2.value(input, { world: worldName }))' in script
    assert '!!inputSummary || (typeof matchMedia === "function" && matchMedia("(max-width: 600px)").matches)' in script
    assert '"Inspect recorded inputs"), inputLine]) : inputLine);' in script


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_short_full_input_stays_in_disclosure_for_duplicate_call():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.expr = text => ({tag:'expr',text});
      A2.el = (tag, attrs, children) => ({tag,attrs,children});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const short = A2.worlds.recordedValue('inputs', 'Inputs: Bot<1, 1, E>', [], true);
      const ordinary = A2.worlds.recordedValue('inputs', 'Inputs: 4', []);
      console.log(JSON.stringify({short,ordinary}));
    """)
    assert result["short"]["tag"] == "details"
    assert result["short"]["children"][1]["text"] == "Inputs: Bot<1, 1, E>"
    assert result["ordinary"] == {"tag": "expr", "text": "Inputs: 4"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_stored_trace_outcomes_keep_string_lookup_and_json_value_paths():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children:[], style:{setProperty() {}},
          appendChild(child) {this.children.push(child)}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      Object.assign(A2, {el, token:(name, opts) => el('token', {name, opts}),
        expr:(content, opts) => el('expr', {content, world:opts.world}),
        value:(content, opts) => el('value', {content, world:opts.world}),
        badge:() => Object.assign(el('badge'), {setAttribute() {}}), register() {}});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const example = {ascii:'f(1)', inputs:[{t:'int',v:1}], outcome:{ok:{t:'int',v:2}},
        trace:{ascii:'f(1)',kind:'root',outcome:'Ok(2)',children:[{kind:'operation',name:'f',outcome:{ok:3}}]}};
      const entry = {name:'f',kind:'operation',layer:1,examples:[example]};
      const card = A2.worlds.entryCard(entry,[entry],'',{},'integer');
      const flatten = node => [node,...(node.children || []).flatMap(flatten)];
      const nodes = flatten(card);
      console.log(JSON.stringify({exprs:nodes.filter(node => node.tag === 'expr').map(node => node.attrs),
        values:nodes.filter(node => node.tag === 'value').map(node => node.attrs),
        labels:nodes.filter(node => node.attrs.text === 'Inputs:').length}));
    """)
    assert {"content": "Ok(2)", "world": "integer"} in result["exprs"]
    assert {"content": {"ok": 3}, "world": "integer"} in result["values"]
    assert {"content": {"t": "int", "v": 1}, "world": "integer"} in result["values"]
    assert result["labels"] == 1


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_road_design_picker_marks_only_current_row():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        return {tag, attrs, children: Array.isArray(children) ? children : [children],
          appendChild(child) {this.children.push(child)}, append(...nodes) {this.children.push(...nodes)},
          replaceChildren(...nodes) {this.children = nodes},
          setAttribute(name, value) {this.attrs[name] = value},
          querySelectorAll(selector) {return selector === 'button' ? this.children.filter(child => child.tag === 'button') : []},
          addEventListener(name, callback) {this.listeners = this.listeners || {}; this.listeners[name] = callback}};
      }
      A2.el = el;
      A2.token = text => el('token', {text});
      A2.expr = text => el('expr', {text});
      A2.badge = () => el('badge');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const mount = el('div');
      catalog.designTower(mount, [
        {name:'Route',kind:'object',layer:1,decl:'obj Route given',example:'Route<1>',value:'Route<1>'},
        {name:'best',kind:'operation',layer:2,decl:'op best L2',example:'best(x)',value:'2'}
      ], 'roads', '../../worlds/designs.json');
      const rail = mount.children[0];
      const states = () => rail.children.map(button => button.attrs['aria-pressed']);
      const initial = states();
      rail.children[0].listeners.click();
      console.log(JSON.stringify({initial, selected:states(), detail:mount.children[2].children[0].children[0].attrs.text,
        live:mount.children[1].attrs.role, announcement:mount.children[1].textContent}));
    """)
    assert result == {"initial": ["false", "true"], "selected": ["true", "false"], "detail": "DESIGN LAYER 1",
                      "live": "status", "announcement": "Selected layer 1: Route."}


def test_world_detail_badges_all_use_records_and_relative_artifact_urls():
    catalog = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    legacy = (ROOT / "docs/assets/js/worlds/legacy-ui.js").read_text()
    assert 'A2.badge("design")' not in catalog
    assert 'A2.badge("legacy")' not in legacy
    assert 'source = mount.dataset.root + "assets/data/worlds_v2/"' in catalog
    assert 'designSource = mount.dataset.root + "worlds/designs.json"' in catalog
    # Notation v3: design towers use their own legend world (design:<world>).
    assert 'designTower(section, world.design.tower, designWorld, designSource, world.parseStatus)' in catalog


def test_dark_world_metadata_contrast_and_minimum_size():
    css = (ROOT / "docs/assets/css/worlds-v2.css").read_text()
    assert '[data-md-color-scheme="slate"] .w2-page { --w2-muted: #cbd5e1; }' in css
    assert '.w2-page .w2-card-status,' in css
    assert '.w2-page .w2-rail-button small,' in css
    assert 'font-size: max(12px, .7rem)' in css

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                  for channel in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    assert (luminance("#cbd5e1") + 0.05) / (luminance("#10172e") + 0.05) >= 4.5


def test_action_design_uses_observation_call_notation():
    designs = json.loads((ROOT / "docs/worlds/designs.json").read_text())
    prompt = designs["worlds"]["action"]["prompt"]
    for probe in ("front_wall", "front_water", "pose"):
        assert f"?{probe}{{state}}" in prompt


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_design_names_do_not_invent_kind_sigils_or_erase_unicode():
    result = run_js(r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      A2.token = (name, options) => ({name, options});
      A2.el = (tag, attrs) => ({tag, text:attrs.text});
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      console.log(JSON.stringify({
        object:catalog.designName({name:'path',kind:'object',layer:2}),
        combination:catalog.designName({name:'walk_until',kind:'combinator',layer:5}),
        invalid:catalog.designName({name:'go \u219d\u27e6step,test\u27e7',kind:'combinator',layer:3}),
        exported:A2.worlds.exportNotation({ascii:'@walk_until[safe_step](robot, 2)'})
      }));
    """)
    assert result["object"]["name"] == "path"
    assert result["combination"]["name"] == "walk_until"
    assert result["invalid"] == {"tag": "span", "text": "Design identifier pending in ASCII"}
    assert result["exported"] == "@walk_until[safe_step](robot, 2)"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_published_showcase_fixtures_are_disclosed():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const action = require(root + '/docs/assets/data/worlds_v2/action.json');
      const pixels = require(root + '/docs/assets/data/worlds_v2/pixels.json');
      console.log(JSON.stringify([catalog.fixtureNotice('action', action), catalog.fixtureNotice('pixels', pixels),
        catalog.fixtureNotice('roads', action), catalog.fixtureNotice('action', {story:[]})]));
    """)
    assert "map is not published in this export" in result[0]
    assert "Grid A0 has published cells" in result[1]
    assert result[2] is None
    assert "not published" in result[3]
    designs = json.loads((ROOT / "docs/worlds/designs.json").read_text())["worlds"]
    assert "learner receives only granted probes" in designs["action"]["prompt"]
    assert "Grid A0 is a published layer-0 constant" in designs["pixels"]["prompt"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_published_fixture_displays_only_exported_public_data():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children:Array.isArray(children) ? children : [children]});
      A2.expr = text => A2.el('expr', {text});
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const action = require(root + '/docs/assets/data/worlds_v2/action.json');
      const pixels = require(root + '/docs/assets/data/worlds_v2/pixels.json');
      const map = catalog.publishedFixture(action);
      const grid = catalog.publishedFixture(pixels);
      console.log(JSON.stringify({map, grid:grid.children[1].attrs.text,
        missing:catalog.publishedFixture({world:'action', story:[]})}));
    """)
    action = json.loads((ROOT / "docs/assets/data/worlds_v2/action.json").read_text())
    pixels = json.loads((ROOT / "docs/assets/data/worlds_v2/pixels.json").read_text())
    assert "judge_view" not in action["story"][0]["examples"][0]
    assert result["map"] is None
    assert result["grid"] == next(item["decl"] for item in pixels["layer0"]["objects"]
                                  if item["decl"].startswith("obj A0 ="))
    assert result["missing"] is None


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_exported_laws_templates_and_dependency_layers_are_distinct_from_story_rows():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children:Array.isArray(children) ? children : [children],
        appendChild(child) {this.children.push(child)}});
      A2.expr = (text, options) => A2.el(options && options.design ? 'code' : 'expr', {text});
      A2.token = (text, options) => A2.el('token', {text, options});
      A2.badge = name => Object.assign(A2.el('badge', {text:name}), {setAttribute() {}});
      A2.register = () => {};
      require(root + '/docs/assets/js/atoms2/tower.js');
      const story = [
        {kind:'law', name:'mul_comm', layer:14, def_layer:4, examples:[], depends_on:[], ascii:'law #mul_comm for bounded integers'},
        {kind:'template', name:'Quot', layer:18, def_layer:1, examples:[], depends_on:[], ascii:'obj Quot[T, canon] = refine T by canon'}
      ];
      const flatten = node => [node, ...(node.children || []).flatMap(flatten)];
      console.log(JSON.stringify(story.map(entry => {
        const nodes = flatten(A2.worlds.entryCard(entry, story, 'integer.json', {}));
        return {name:A2.worlds.identifier(entry), kind:nodes[0].attrs.class,
          position:nodes.find(node => node.attrs.text?.startsWith('Tower position:')).attrs.text,
          layer:nodes.find(node => node.attrs.text?.startsWith('Definition layer:')).attrs.text,
          tokens:nodes.filter(node => node.tag === 'token').map(node => node.attrs),
          declarations:nodes.filter(node => node.tag === 'expr').map(node => node.attrs.text),
          designTexts:nodes.filter(node => node.tag === 'code').map(node => node.attrs.text)};
      })));
    """)
    assert result[0]["name"] == "#mul_comm"
    assert result[0]["position"] == "Tower position: row 14"
    assert result[0]["layer"] == "Definition layer: L4 (computed)"
    assert result[1]["position"] == "Tower position: row 18"
    assert result[1]["layer"] == "Definition layer: L1 (computed)"
    assert result[1]["tokens"][0]["options"]["kind"] == "template"
    assert "obj Quot[T, canon] = refine T by canon" not in result[1]["declarations"]
    assert "obj Quot[T, canon] = refine T by canon" in result[1]["designTexts"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_cross_world_bridges_only_appear_on_participating_worlds():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      globalThis.location = {href:'https://example.test/worlds/pixels/'};
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children:Array.isArray(children) ? children : [children],
        appendChild(child) {this.children.push(child)}});
      A2.token = (text, options) => A2.el('token', {text, options});
      A2.expr = text => A2.el('expr', {text});
      A2.value = input => A2.el('value', {input});
      A2.badge = () => A2.el('badge');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const bridge = {name:'beat_row', source_world:'rhythm@1', target_world:'pixels@1',
        definition:'Convert beat accents to grid cells.', decl:'bridge ~beat_row: Rhythm -> Grid',
        examples:[{text:'~beat_row(Rhythm<2,0,1>)', outcome:{ok:{t:'int', v:3}}}]};
      const mount = {dataset:{root:'../../'}};
      const panel = catalog.bridgePanel(mount, {world:'pixels', bridges:[bridge]});
      const flatten = node => [node, ...(node.children || []).flatMap(flatten)];
      console.log(JSON.stringify({unrelated:catalog.bridgePanel(mount, {world:'roads', bridges:[bridge]}),
        tokens:flatten(panel).filter(node => node.tag === 'token').map(node => node.attrs),
        urls:flatten(panel).filter(node => node.tag === 'a').map(node => node.attrs.href)}));
    """)
    assert result["unrelated"] is None
    assert result["tokens"] == [{"text": "~beat_row", "options": {"kind": "bridge", "origin": "invented", "world": "pixels"}}]
    assert result["urls"] == ["https://example.test/assets/data/worlds_v2/bridges/bridges.json"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_bridge_export_uses_known_path_without_index_pointer_and_failure_is_visible():
    result = run_js("""
      const root = process.argv[1];
      require(root + '/docs/assets/js/atoms2/kit.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const calls = [];
      const fetcher = url => {calls.push(url); return Promise.resolve({ok:false})};
      Promise.all([
        catalog.loadBridges({}, '/assets/data/worlds_v2/', fetcher),
        catalog.loadBridges({bridges:{file:'../outside.json'}}, '/assets/data/worlds_v2/', fetcher),
        catalog.loadBridges({bridges:{file:'bridges/bridges.json'}}, '/assets/data/worlds_v2/', fetcher)
      ]).then(records => console.log(JSON.stringify({calls, notes:records.map(catalog.bridgeNotice)})));
    """)
    assert result["calls"] == ["/assets/data/worlds_v2/bridges/bridges.json"] * 3
    assert all("Bridge export not available" in note for note in result["notes"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_bridge_export_fallback_with_and_without_file(tmp_path):
    bridge_file = tmp_path / "bridges" / "bridges.json"
    bridge_file.parent.mkdir()
    bridge_file.write_text(json.dumps({"story": [{"name": "beat_row"}]}))
    script = """
      const fs = require('fs/promises');
      const catalog = require(process.argv[1] + '/docs/assets/js/worlds/catalog-ui.js');
      const base = process.argv[2] + '/';
      const fetcher = async url => {
        try { return {ok:true, json:async () => JSON.parse(await fs.readFile(url, 'utf8'))}; }
        catch (error) { if (error.code === 'ENOENT') return {ok:false}; throw error; }
      };
      (async () => {
        const found = await catalog.loadBridges({}, base, fetcher);
        await fs.unlink(base + 'bridges/bridges.json');
        const missing = await catalog.loadBridges({}, base, fetcher);
        console.log(JSON.stringify({found, missing, foundNotice:catalog.bridgeNotice(found),
          missingNotice:catalog.bridgeNotice(missing)}));
      })().catch(error => {console.error(error); process.exitCode = 1;});
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT), str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["found"] == {"story": [{"name": "beat_row"}], "available": True}
    assert output["foundNotice"] == ""
    assert output["missing"] == {"story": [], "available": False}
    assert "Bridge export not available" in output["missingNotice"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_declared_bridge_export_renders_records():
    result = run_js("""
      const root = process.argv[1];
      require(root + '/docs/assets/js/atoms2/kit.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      catalog.loadBridges({bridges:'bridges/bridges.json'}, '/data/',
        () => Promise.resolve({ok:true, json:() => Promise.resolve({story:[{name:'beat_row'}]})}))
        .then(record => console.log(JSON.stringify(record)));
    """)
    assert result == {"story": [{"name": "beat_row"}], "available": True}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_action_case_headings_expose_map_and_facing_without_expansion():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const cases = require(root + '/docs/assets/data/worlds_v2/action.json').story
        .find(row => row.name === 'safe_step');
      console.log(JSON.stringify(cases.examples.map((example, index) =>
        A2.worlds.caseHeading(cases, example, index))));
    """)
    assert "MAP M2 / FACING E" in result[0]
    assert "MAP M1 / FACING N" in result[1]


def test_roads_current_core_scope_is_separate_from_historical_export():
    script = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert script.index('"See the current-core panel for the artifact') < script.index(
        '"Recorded outcome", "w2-eyebrow"')
    assert '"The Metro cases below run through the current core.' in script
    tower = (ROOT / "docs/assets/js/atoms2/tower.js").read_text()
    assert 'This historical export is not a current-core check.' not in tower


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_compressed_trace_outcomes_are_labeled_without_object_coercion():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      console.log(JSON.stringify({repr:A2.worlds.outcomeNotation({ok:{repr:'Card(grid, pixels, (mask,))'}}),
        elided:A2.worlds.outcomeNotation({ok:{elided_value:'Survey', chars:20912}}),
        tuple:A2.worlds.outcomeNotation({ok:{t:'tuple', v:[{t:'int', v:29},{t:'int',v:9}]}}),
        ordinary:A2.worlds.outcomeNotation({ok:{t:'int', v:21}})}));
    """)
    # Notation v3: an unregistered tuple has no safe display formula and cannot expose raw JSON.
    assert result == {"repr": "Ok(Card(grid, pixels, (mask,)))",
                      "elided": "Ok(value elided (20912 chars): Survey)",
                      "tuple": "Ok(value not available)",
                      "ordinary": "Ok(21)"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_all_exported_cases_render_decoded_inputs_results_and_traces():
    result = run_js(r"""
      const fs = require('fs');
      const root = process.argv[1];
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children: [], style: {setProperty() {}}, appendChild(child) {this.children.push(child)},
          replaceChildren(...items) {this.children = items}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      Object.assign(A2, {el, token: (text) => el('token', {text}), expr: (text, options) => el('expr', {text, given:options && options.given}),
        value: (input, options) => el('value', {input, world:options.world}),
        badge: (name) => Object.assign(el('badge', {text:name}),
          {textContent:name, setAttribute(key, value) {this.attrs[key] = value}}), register() {}});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const index = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds_v2/index.json'));
      let total = 0, rendered = 0;
      function flatten(node) {return [node, ...(node.children || []).flatMap(flatten)]}
      for (const item of index.worlds) {
        const world = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds_v2/' + item.file));
        for (const entry of world.story) {
          const nodes = flatten(A2.worlds.entryCard(entry, world.story, item.file, world.decl, item.world));
          const badges = nodes.filter(node => node.tag === 'badge');
          const recorded = A2.hasRecordedScope(entry.evidence);
          if (badges.some(node => node.attrs.text !== 'design' ||
            /checked|promoted/i.test(node.textContent)) ||
            (recorded && !badges.length) || (!recorded &&
              !nodes.some(node => node.attrs.text === 'scope not recorded')))
            throw new Error(item.world + ':' + entry.name + ' rendered an unverified claim');
          const cases = nodes.filter(node => node.attrs.class === 'w2-case');
          total += entry.examples.length;
          rendered += cases.length;
          for (const [index, example] of entry.examples.entries()) {
            const trace = example.trace;
            const assertEqual = (actual, expected, field) => {
              if (JSON.stringify(actual) !== JSON.stringify(expected))
                throw new Error(item.world + ':' + entry.name + ' mismatched ' + field);
            };
            const comparable = (traceValue, resultValue) => {
              if (traceValue && traceValue.t === 'int' && typeof resultValue === 'number')
                return traceValue.v;
              if (traceValue && traceValue.t === 'bool' && typeof resultValue === 'boolean' &&
                  Array.isArray(traceValue.f) && traceValue.f.length === 0)
                return traceValue.tag === 'true';
              if (traceValue && traceValue.t === 'tuple' && resultValue &&
                  ['List', 'Pair'].includes(resultValue.t) && Array.isArray(resultValue.f))
                return comparable({t:resultValue.t, tag:resultValue.tag, f:traceValue.v.map((value, position) =>
                  comparable(value, resultValue.f[position]))}, resultValue);
              if (Array.isArray(traceValue)) return traceValue.map((value, position) =>
                comparable(value, resultValue && resultValue[position]));
              if (traceValue && typeof traceValue === 'object')
                return Object.fromEntries(Object.keys(traceValue).sort().map(key =>
                  [key, comparable(traceValue[key], resultValue && resultValue[key])]));
              return traceValue;
            };
            const caseNodes = flatten(cases[index]);
            if (trace && trace.kind !== 'root' && !(trace.kind === 'expression' && trace.name == null) &&
              (!(trace.name === entry.name || (trace.name || '').startsWith(entry.name + '.')) || trace.kind !== entry.kind))
              throw new Error(item.world + ':' + entry.name + ' mismatched trace identity');
            if (!trace) {
              if (caseNodes.some(node => node.attrs.class === 'w2-trace-line'))
                throw new Error(item.world + ':' + entry.name + ' invented missing trace');
            } else if (trace.elided && !trace.outcome && !(trace.children || []).length) {
              if (A2.worlds.hasTrace(example)) throw new Error('elided trace offered as expandable');
            } else if (trace.outcome && trace.outcome.ok && trace.outcome.ok.elided_value) {
              if (!trace.outcome.ok.chars || !example.outcome.ok) throw new Error('missing trace compression metadata');
            } else if (trace.outcome && trace.outcome.ok && trace.outcome.ok.repr) {
              if (!example.outcome.ok || !(trace.outcome.ok.repr === example.outcome.ok.repr) &&
                  !(Array.isArray(example.outcome.ok) &&
                    (trace.outcome.ok.repr.startsWith('Run(') ||
                     (trace.outcome.ok.repr.startsWith('[') && trace.outcome.ok.repr.endsWith(']')))) &&
                  !trace.outcome.ok.repr.includes(example.outcome.ok.t))
                throw new Error(item.world + ':' + entry.name + ' mismatched trace representation');
            } else if (trace.outcome && trace.outcome.ok && trace.outcome.ok.redacted) {
              if (trace.outcome.ok.redacted !== 'private kitchen data' || !example.outcome.ok)
                throw new Error('invalid private trace redaction');
            } else if (trace.outcome && trace.outcome.ok && trace.outcome.ok.t === 'tuple' &&
                example.outcome.ok && example.outcome.ok.t === 'tuple' &&
                trace.outcome.ok.v.some(value => value.repr) &&
                JSON.stringify(trace.outcome.ok) !== JSON.stringify(example.outcome.ok)) {
              if (trace.outcome.ok.v.length !== example.outcome.ok.v.length ||
                  trace.outcome.ok.v.some((value, position) =>
                    value.repr && (typeof value.repr !== 'string' || !value.repr.includes(example.outcome.ok.v[position].t))))
                throw new Error(item.world + ':' + entry.name + ' invalid compressed tuple trace values');
            } else if (trace.outcome && trace.outcome.ok && trace.outcome.ok.t === 'tuple' &&
                example.outcome.ok && example.outcome.ok.t === 'List') {
              if (trace.outcome.ok.v.every(value => !value.repr))
                assertEqual(comparable(trace.outcome, example.outcome),
                  comparable(example.outcome, example.outcome), 'trace tuple/list contents');
              else if (trace.outcome.ok.v.length !== example.outcome.ok.f.length ||
                trace.outcome.ok.v.some(value => typeof value.repr !== 'string'))
                throw new Error('missing compressed tuple/list trace values');
            } else if (trace) assertEqual(comparable(trace.outcome, example.outcome),
              comparable(example.outcome, example.outcome), 'trace outcome');
            if (trace) assertEqual(trace.steps, example.steps, 'trace cost');
            const expressions = caseNodes.filter(node => node.tag === 'expr').map(node => node.attrs.text);
            const outcome = A2.worlds.outcomeNotation(example.outcome);
            const call = A2.worlds.exportNotation(example);
            if (call && expressions[0] !== call)
              throw new Error(item.world + ':' + entry.name + ' invented call from export');
            if (!caseNodes.some(node => node.tag === 'value' && node.attrs.input === example.outcome) ||
                caseNodes.filter(node => node.tag === 'value').length < (example.inputs || []).length + 1 ||
                !caseNodes.some(node => node.attrs.text === 'Inputs:'))
              throw new Error(item.world + ':' + entry.name + ' missing decoded input/result');
            const inputs = caseNodes.find(node => node.attrs.class === 'w2-input-values');
            if (!inputs || inputs.children.slice(1).some((node, position) =>
              node.tag !== 'value' || node.attrs.input !== example.inputs[position] || node.attrs.world !== item.world))
              throw new Error(item.world + ':' + entry.name + ' lost world-scoped input values');
            if (caseNodes.some(node => node.attrs.text === 'notation pending from the worlds export'))
              throw new Error(item.world + ':' + entry.name + ' repeated pending notation');
            if (!call && !caseNodes.some(node => node.tag === 'token' && node.attrs.text === A2.worlds.identifier(entry)))
              throw new Error(item.world + ':' + entry.name + ' missing recorded identifier');
            const given = A2.worlds.givenNames(world.decl);
            if (caseNodes.filter(node => node.tag === 'expr').some(node => JSON.stringify(node.attrs.given) !== JSON.stringify(given)))
              throw new Error(item.world + ':' + entry.name + ' missing given provenance');
            const traceNodes = caseNodes.filter(node => node.attrs.class === 'w2-trace-line');
            const traceLines = trace ? A2.worlds.traceLines(trace, [], 0, call) : [];
            for (const [position, line] of traceLines.entries()) {
              if (!traceNodes[position] || line.outcome == null) continue;
              const nodes = flatten(traceNodes[position]);
              // Notation v3: the judge-only placeholder is plain text, never a formula.
              if (line.outcome === 'sealed (judge-only)' ?
                !nodes.some(node => node.attrs && node.attrs.text === line.outcome) :
                typeof line.outcome === 'string' ?
                !nodes.some(node => node.tag === 'expr' && node.attrs.text === line.outcome) :
                !nodes.some(node => node.tag === 'value' && node.attrs.input === line.outcome && node.attrs.world === item.world))
                throw new Error(item.world + ':' + entry.name + ' lost recorded trace outcome');
            }
            if (trace && typeof trace.elided === 'string' && !(trace.children || []).length) {
              if (traceNodes.length || caseNodes.some(node => node.tag === 'summary' && node.attrs.text.includes('trace steps')) ||
                  !caseNodes.some(node => node.attrs.text === 'Trace not recorded (' + example.steps +
                    ' recorded layer-0 steps). ' + trace.elided))
                throw new Error(item.world + ':' + entry.name + ' suppressed trace offered as expandable');
              continue;
            }
            for (const [position, line] of traceLines.entries()) {
              if (line.elided > 0 && !traceNodes[position].children.some(node => node.attrs.text ===
                '+' + line.elided.toLocaleString('en-US') + ' calls not shown'))
                throw new Error(item.world + ':' + entry.name + ' lost elided calls');
              if (typeof line.elided === 'string' && !traceNodes[position].children.some(node =>
                node.attrs.text === 'Recorded trace note: ' + line.elided))
                throw new Error(item.world + ':' + entry.name + ' lost suppressed trace marker');
            }
            if (trace && (!traceNodes.length || !traceNodes[0].children.some(node =>
              node.tag === 'small' && node.attrs.text.endsWith(example.steps + ' steps'))))
              throw new Error(item.world + ':' + entry.name + ' mismatched rendered trace cost');
            if (trace && !caseNodes.some(node => node.tag === 'summary' && node.attrs.text.includes('trace steps')))
              throw new Error(item.world + ':' + entry.name + ' missing trace');
            if (expressions.some(text => /[^\x20-\x7e]/.test(text))) throw new Error('Non-ASCII notation');
          }
        }
      }
      console.log(JSON.stringify({total, rendered}));
    """)
    expected = sum(len(row["examples"]) for item in json.loads((ROOT / "docs/assets/data/worlds_v2/index.json").read_text())["worlds"]
                   for row in json.loads((ROOT / "docs/assets/data/worlds_v2" / item["file"]).read_text())["story"])
    assert result == {"total": expected, "rendered": expected}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_elided_calls_are_reported_at_their_parent_trace_node():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const dice = require(root + '/docs/assets/data/worlds_v2/dice.json');
      const shadows = require(root + '/docs/assets/data/worlds_v2/shadows.json');
      const summarize = world => world.story.flatMap(entry => entry.examples.map(example => {
        const nodes = A2.worlds.traceLines(example.trace, [], 0);
        return {hidden:nodes.reduce((total, node) => total + (node.elided || 0), 0),
          marked:nodes.filter(node => node.elided > 0).length};
      }));
      console.log(JSON.stringify({dice:summarize(dice), shadows:summarize(shadows)}));
    """)
    for world in ("dice", "shadows"):
        assert sum(case["hidden"] for case in result[world]) > 0
        assert sum(case["marked"] for case in result[world]) > 0


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_trace_uses_only_exported_ascii_notation():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const trace = {kind:'root', outcome:{ok:{t:'int',v:8}}, children:[
        {name:'step', kind:'operation', ascii:'step(8)', outcome:{ok:{t:'int',v:8}}, children:[]},
        {name:'other', kind:'operation', outcome:{ok:{t:'int',v:8}}, children:[]}]};
      console.log(JSON.stringify(A2.worlds.traceLines(trace, [], 0, 'call(8)').map(node => node.call)));
    """)
    assert result == ["call(8)", "step(8)", None]


def test_undeclared_trace_frames_are_not_atom_chips():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      console.log(JSON.stringify([
        A2.worlds.traceLabel('operation', false),
        A2.worlds.traceLabel('operation', true),
        A2.worlds.traceLabel('observation', false)]));
    """)
    assert result == ['local loop', None, 'Recorded call']


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_combinator_call_requires_exported_binding_notation():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const worlds = A2.worlds;
      console.log(JSON.stringify({
        valid:worlds.exportNotation({ascii:'@walk_until[safe_step, is_zero](robot, 2)'}, 'combinator'),
        nested:worlds.exportNotation({ascii:'@explore[@scan[turn_right, sense], safe_step](robot)'}, 'combinator'),
        missingBinding:worlds.exportNotation({ascii:'@walk_until(robot, 2)'}, 'combinator'),
        rootCall:worlds.exportNotation({kind:'root',ascii:'@walk_until(robot, 2)'}),
        rawCall:worlds.exportNotation({name:'walk_until',inputs:[{t:'int',v:2}]}, 'combinator'),
        trace:worlds.traceLines({kind:'root',outcome:{ok:{t:'int',v:2}},children:[
          {kind:'combinator',ascii:'@walk_until(robot, 2)',outcome:{ok:{t:'int',v:2}}},
          {kind:'combinator',ascii:'@walk_until[safe_step](robot, 2)',outcome:{ok:{t:'int',v:2}}}
        ]}, [], 0).map(item => item.call)
      }));
    """)
    assert result == {"valid": "@walk_until[safe_step, is_zero](robot, 2)",
                      "nested": "@explore[@scan[turn_right, sense], safe_step](robot)",
                      "missingBinding": None, "rootCall": None, "rawCall": None,
                      "trace": [None, None, "@walk_until[safe_step](robot, 2)"]}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_missing_definition_layer_and_ascii_call_use_exact_export_fields():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children:[], style:{setProperty() {}}, appendChild(child) {this.children.push(child)},
          replaceChildren(...children) {this.children = children}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      Object.assign(A2, {el, value:(input, options) => el('value', {input, world:options.world}), token:(value, options) => el('token', {text:value, ...options}),
        expr:(value, options) => el('expr', {text:value, given:options && options.given}),
        badge:() => Object.assign(el('badge'), {setAttribute() {}}), register() {}});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const action = require(root + '/docs/assets/data/worlds_v2/action.json');
      const original = action.story[0];
      const withAscii = structuredClone(original);
      withAscii.examples[0].ascii = '?walkable{Robot<1>}';
      withAscii.examples[0].trace.ascii = '?walkable{Robot<1>}';
      function flatten(node) {return [node, ...(node.children || []).flatMap(flatten)]}
      const pending = flatten(A2.worlds.entryCard(original, action.story, 'action.json', action.decl));
      const recorded = flatten(A2.worlds.entryCard(withAscii, action.story, 'action.json', action.decl));
      console.log(JSON.stringify({pending:pending.map(node => node.attrs.text).filter(Boolean),
        names:pending.filter(node => node.tag === 'token').map(node => ({text:node.attrs.text, kind:node.attrs.kind})),
        recorded:recorded.filter(node => node.tag === 'expr').map(node => node.attrs.text),
        given:recorded.filter(node => node.tag === 'expr').map(node => node.attrs.given)}));
    """)
    assert all("Definition layer: not recorded" not in text and "L?" not in text for text in result["pending"])
    assert "notation pending from the worlds export" not in result["pending"]
    assert {"text": "?front_clear", "kind": "observation"} in result["names"]
    assert "?walkable{Robot<1>}" in result["recorded"]
    assert all("?front_wall" in names and "Maze" in names for names in result["given"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tower_rail_omits_unknown_layer_chip():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children:[], style:{setProperty() {}},
          appendChild(child) {this.children.push(child)}, append(...children) {this.children.push(...children)},
          replaceChildren(...children) {this.children = children},
          addEventListener() {}, setAttribute(key, value) {this.attrs[key] = value},
          querySelectorAll(tagName) {return this.children.filter(child => child.tag === tagName)}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      Object.assign(A2, {el, value:input => el('value', {input}), token:(value) => el('token', {text:value}), expr:(value) => el('expr', {text:value}),
        badge:() => Object.assign(el('badge'), {setAttribute() {}}), register() {}});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const action = require(root + '/docs/assets/data/worlds_v2/action.json');
      const container = el('div');
      A2.worlds.tower(container, action, 'action.json');
      console.log(JSON.stringify(container.children[0].children.map(button => ({
        caption:button.children[0].attrs.text,
        name:button.children[1].attrs.text}))));
    """)
    assert all("L?" not in row["caption"] for row in result)
    assert all(row["caption"].startswith("ROW ") for row in result)
    assert [row["name"] for row in result] == [
        ("?" if entry["kind"] == "observation" else "@" if entry["kind"] == "combinator" else "") + entry["name"]
        for entry in json.loads((ROOT / "docs/assets/data/worlds_v2/action.json").read_text())["story"]]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_mismatched_export_trace_is_rejected() -> None:
    result = run_js(r"""
      const root = process.argv[1];
      const action = require(root + '/docs/assets/data/worlds_v2/action.json');
      const example = structuredClone(action.story[0].examples[0]);
      function check(trace) {
        const firstCall = trace.children[0];
        if (JSON.stringify(trace.outcome) !== JSON.stringify(example.outcome) ||
            trace.steps !== example.steps || JSON.stringify(firstCall.inputs) !== JSON.stringify(example.inputs))
          throw new Error('Trace does not match exported example');
      }
      check(example.trace);
      const rejected = [];
      for (const field of ['inputs', 'outcome', 'steps']) {
        const broken = structuredClone(example.trace);
        if (field === 'inputs') broken.children[0].inputs = [];
        if (field === 'outcome') broken.outcome = {bottom: 'wrong result'};
        if (field === 'steps') broken.steps += 1;
        try { check(broken); rejected.push(false); } catch (error) { rejected.push(true); }
      }
      console.log(JSON.stringify(rejected));
    """)
    assert result == [True, True, True]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tower_uses_shared_value_formatter_for_exported_cards() -> None:
    result = run_js(r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const dice = require(root + '/docs/assets/data/worlds_v2/dice.json');
      const outcome = dice.story[0].examples[0].outcome;
      console.log(JSON.stringify({same: A2.worlds.valueNotation === A2.formatValue,
        outcome: A2.worlds.outcomeNotation(outcome), value: A2.formatValue(outcome.ok)}));
    """)
    assert result == {"same": True, "outcome": "Ok(Frac.rational<1, 36>)", "value": "Frac.rational<1, 36>"}


def test_tower_badges_never_upgrade_recorded_hashes(tmp_path: Path) -> None:
    fixture = tmp_path / "mismatched-world.json"
    fixture.write_text(json.dumps({
        "schema": "opulse.world_v2_export/1",
        "decl": {"lock": {"world_hash": "current-hash"}},
        "story": [{"name": "check", "kind": "operation", "layer": 1, "def_layer": 1,
                   "status": "promoted", "evidence": {"method": "exhaustive", "world_hash": "older-hash",
                                "scope": {"description": "Eight cases", "size": 8,
                                          "checked": {"size": 8, "sha256": "a" * 64}}},
                   "examples": [{"inputs": [], "outcome": {"ok": {"t": "int", "v": 1}}, "steps": 1}]}],
    }))
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const world = require(process.argv[2]);
      A2.badge = (status, options) => ({status, options, textContent:status,
        setAttribute(key, value) {this[key] = value}});
      const entry = world.story[0];
      function snapshot(decl) {
        const badge = A2.worlds.towerBadge(entry, '../export.json', decl);
        const drawer = A2.evidenceRecord(badge.options.record);
        return {status:badge.status, text:badge.textContent, aria:badge['aria-label'],
          hash:drawer.artifact.worldHash, description:drawer.description,
          artifact:drawer.artifact.file, href:badge.options.record.artifact.href};
      }
      const mismatch = snapshot(world.decl);
      const match = snapshot({lock:{world_hash:'older-hash'}});
      const missingLock = snapshot({lock:{}});
      delete entry.evidence.world_hash;
      const missingEvidence = snapshot(world.decl);
      console.log(JSON.stringify({mismatch, match, missingLock, missingEvidence}));
    """, str(fixture))
    warning = "Historical export (outcome only)"
    for key in ("mismatch", "match", "missingLock", "missingEvidence"):
        assert result[key]["status"] == "design"
        assert result[key]["text"] == warning
        assert result[key]["aria"] == warning + ". View evidence details"
        assert result[key]["artifact"] == "export.json"
        assert result[key]["href"] == "../export.json"
        assert "Stored export declaration lock hash: " in result[key]["description"]
        assert "Evidence world hash: " in result[key]["description"]
        assert "Recorded status: promoted." in result[key]["description"]
        assert "Current declaration hash: not available in the browser (not recomputed)." in result[key]["description"]
    assert "current-hash" in result["mismatch"]["description"]
    assert "older-hash" in result["mismatch"]["description"]
    assert result["mismatch"]["hash"] == "older-hash"
    assert "Stored export declaration lock hash: not recorded." in result["missingLock"]["description"]
    assert result["missingEvidence"]["hash"] is None
    assert result["match"]["description"].count("older-hash") == 2


def test_real_exported_towers_never_render_checked_or_promoted_badges() -> None:
    result = run_node("""
      const fs = require('fs');
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      A2.el = (tag, attrs = {}, content) => ({tag, attrs, textContent:content || attrs.text || ''});
      A2.badge = (status, options) => ({status, options, setAttribute() {}, textContent:status});
      const index = require(root + '/docs/assets/data/worlds_v2/index.json');
      const verdicts = index.worlds.flatMap(item => {
        const world = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds_v2/' + item.file));
        return world.story.map(entry => {
          const badge = A2.worlds.towerBadge(entry, item.file, world.decl);
          if (!A2.hasRecordedScope(entry.evidence))
            return {status: null, label: badge.textContent || badge.attrs && badge.attrs.text,
              recorded: entry.status, lock: world.decl.lock.world_hash};
          const drawer = A2.evidenceRecord(badge.options.record);
          return {status: badge.status, label: badge.textContent, description: drawer.description,
            method: drawer.method, recorded: entry.status, hash: drawer.artifact.worldHash,
            lock: world.decl.lock.world_hash};
        });
      });
      console.log(JSON.stringify(verdicts));
    """)
    expected = sum(len(json.loads((ROOT / "docs/assets/data/worlds_v2" / item["file"]).read_text())["story"])
                   for item in json.loads((ROOT / "docs/assets/data/worlds_v2/index.json").read_text())["worlds"])
    assert len(result) == expected
    for verdict in result:
        if verdict["status"] is None:
            assert verdict["label"] == "scope not recorded"
            continue
        assert verdict["status"] == "design"
        assert "checked" not in verdict["label"].lower()
        assert "promoted" not in verdict["label"].lower()
        assert verdict["label"] in {"Historical export", "Historical export (outcome only)"}
        assert f"Recorded status: {verdict['recorded']}." in verdict["description"]
        assert f"Stored export declaration lock hash: {verdict['lock']}." in verdict["description"]
        assert "Current declaration hash: not available in the browser (not recomputed)." in verdict["description"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_all_legacy_worlds_have_worked_examples_with_rules_and_values():
    result = run_js(r"""
      const fs = require('fs'); const root = process.argv[1];
      globalThis.A2 = {worlds:{ascii: text => String(text).replace(/[^\x20-\x7e]/g, '').trim()}};
      const legacy = require(root + '/docs/assets/js/worlds/legacy-ui.js');
      let worlds = 0, examples = 0;
      for (const id of legacy.ids) {
        const world = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds/' + id + '.json'));
        const selected = legacy.worked(world);
        if (selected.length !== 4) throw new Error(id + ': empty or short example list');
        for (const operator of selected) {
          if (!legacy.rule(world, operator) || !operator.examples[0].output) throw new Error(id + ': missing rule/value');
          if (/[^\x20-\x7e]/.test(legacy.rule(world, operator))) throw new Error(id + ': non-ASCII rule');
        }
        worlds++; examples += selected.length;
      }
      console.log(JSON.stringify({worlds, examples}));
    """)
    assert result == {"worlds": 12, "examples": 48}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_modality_filter_uses_its_option_source():
    result = run_js(r"""
      const root = process.argv[1];
      globalThis.A2 = {worlds: {tags: world => world.tags || {}, fields: ['modalities'],
        tagField: (world, field) => (world.tags || {})[field],
        openKinds: () => [], status: () => 'design', kindCounts: () => ({}), tagValue: String}};
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const worlds = [{world:'audio', title:'Audio', wave:2, tags:{}, design:{modalities:['audio']}},
        {world:'image', title:'Image', wave:2, tags:{modalities:['image']}, design:{modalities:['audio']}}];
      console.log(JSON.stringify({options: worlds.map(catalog.modalities),
        results: catalog.filterWorlds(worlds, {modalities:'audio'}).map(world => world.world)}));
    """)
    assert result == {"options": [["audio"], ["image"]], "results": ["audio"]}


EXPORTS = ROOT / "docs/assets/data/worlds_v2"


def run_node(script: str, *args: str) -> dict:
    if NODE is None:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", script, str(ROOT), *args],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_exported_towers_use_real_dependencies_and_six_kinds() -> None:
    worlds = json.loads((EXPORTS / "index.json").read_text())["worlds"]
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const index = require(root + '/docs/assets/data/worlds_v2/index.json');
      console.log(JSON.stringify(index.worlds.map(item => {
        const world = require(root + '/docs/assets/data/worlds_v2/' + item.file);
        return {id: world.world, status: A2.worlds.status(world), counts: A2.worlds.kindCounts(world),
          edges: world.story.map(row => A2.worlds.dependencies(world.story, row))};
      })));
    """)
    assert len(result) == len(worlds) == 26
    assert {"op_only", "obs_only", "comb_only", "obj_op", "comb_obs", "obj_only"} <= {
        item["world"] for item in worlds}
    for item, actual in zip(worlds, result):
        world = json.loads((EXPORTS / item["file"]).read_text())
        assert actual["id"] == world["world"]
        assert actual["status"] == "exported"
        assert sum(actual["counts"].values()) == len(world["story"])
        assert set(actual["counts"]) == {"object", "operation", "combinator", "observation", "law", "bridge"}
        for row, edges in zip(world["story"], actual["edges"]):
            assert [edge["name"] for edge in edges] == row["depends_on"]
            assert all(edge["invented"] == (edge["name"].split(".")[0] in {entry["name"] for entry in world["story"]})
                       for edge in edges)
            for edge in edges:
                if edge["invented"]:
                    target = next(entry for entry in world["story"] if entry["name"] == edge["name"].split(".")[0])
                    assert edge["row"] == target["layer"] and edge.get("layer") == target.get("def_layer")
                    assert edge["kind"] == ("object" if target["kind"] == "template" else target["kind"])


def test_scope_open_kinds_and_missing_export_are_honest() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const roads = require(root + '/docs/assets/data/worlds_v2/roads.json');
      console.log(JSON.stringify({scope:A2.worlds.scope(roads.story[0]),
        missing:A2.worlds.status({story:[]}), open:A2.worlds.openKinds(roads),
        counts:A2.worlds.kindCounts({story:[{kind:'law'},{kind:'bridge'}]}),
        inventedLabel:A2.worlds.label}));
    """)
    assert "all 256 weightings" in result["scope"]
    assert "fixed connected 4-node, 4-road graph" in result["scope"]
    assert result["missing"] == "design"
    assert set(result["open"]) == {"object", "operation", "combinator", "observation"}
    assert result["counts"]["law"] == result["counts"]["bridge"] == 1
    assert "inventedLabel" not in result


def test_hand_copied_catalogue_was_retired() -> None:
    assert not (ROOT / "docs/assets/js/atoms2/catalog.js").exists()
    assert "atoms2/catalog.js" not in (ROOT / "mkdocs.yml").read_text()


def test_structured_tags_are_readable_and_filterable() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      console.log(JSON.stringify({scale:A2.worlds.tagValue({states:120, definitions:8}),
        uses:A2.worlds.tagValue(['evaluation','teaching'])}));
    """)
    assert result == {"scale": "states: 120; definitions: 8", "uses": "evaluation, teaching"}


def test_partial_and_list_tags_do_not_claim_tags_are_pending() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      globalThis.document = {createElement(tag) {
        return {tag, children:[], setAttribute(key, value) {this[key] = value},
          appendChild(child) {this.children.push(child)}, textContent:''};
      }};
      const kitchen = require(root + '/docs/assets/data/worlds_v2/kitchen.json');
      const partial = {world:'computer', title:'Computer', tags:{domain:'computation'}, story:[]};
      const chips = world => A2.worlds.fieldChips(world, ['domain', 'modalities', 'open_kinds'])
        .children.map(child => child.textContent);
      console.log(JSON.stringify({kitchen:chips(kitchen), partial:chips(partial),
        matches:catalog.filterWorlds([kitchen,partial], {tags:'planning'}).map(world => world.world)}));
    """)
    assert all("tags: " + tag in result["kitchen"] for tag in
               ("planning", "resources", "partial-observation", "search"))
    assert "tags pending" not in result["kitchen"] + result["partial"]
    assert "domain: computation" in result["partial"]
    assert result["matches"] == ["kitchen"]


def test_designed_identifier_and_recorded_poses_are_distinct() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children:[], style:{setProperty() {}},
          appendChild(child) {this.children.push(child)}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      Object.assign(A2, {el, value:input => el('value', {input}), token: text => el('token', {text}), expr: text => el('expr', {text}),
        badge: () => Object.assign(el('badge'), {setAttribute() {}}), register() {}});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const action = require(root + '/docs/assets/data/worlds_v2/action.json');
      const safe = action.story.find(entry => entry.name === 'safe_step');
      const card = A2.worlds.entryCard(safe, action.story, 'action.json', action.decl);
      const cases = card.children.filter(node => node.attrs.class === 'w2-case');
      console.log(JSON.stringify({identifier:catalog.designName({name:'@failures',kind:'combinator',layer:4}).attrs.text,
        headings:cases.map(node => node.children[0].attrs.text)}));
    """)
    assert result["identifier"] == "@failures"
    assert "POSE 1,1,E" in result["headings"][0]
    assert "POSE 1,1,N" in result["headings"][1]


def test_mobile_featured_routes_precede_catalog_cards() -> None:
    css = (ROOT / "docs/assets/css/worlds-v2.css").read_text()
    mobile = css[css.index('@media (max-width: 600px) { .w2-page:has(> .w2-catalog-tools)'):
                 css.index('@media (max-width: 600px) { .w2-spotlight')]
    assert mobile.index('> .w2-contrast { order: 1;') < mobile.index('> #catalog { order: 3;')
    assert '.w2-card-tower summary { cursor: pointer;' in css


def test_catalog_starts_short_but_filtered_worlds_remain_discoverable() -> None:
    result = run_node("""
      const root = process.argv[1];
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const matches = Array.from({length: 21}, (_, index) => index);
      console.log(JSON.stringify({initial:catalog.visibleWorlds(matches, {}, false).length,
        searched:catalog.visibleWorlds(matches, {q:'roads'}, false).length,
        expanded:catalog.visibleWorlds(matches, {}, true).length}));
    """)
    assert result == {"initial": 9, "searched": 21, "expanded": 21}


def test_tagged_export_renders_chips_and_filters_without_catalog_changes(tmp_path: Path) -> None:
    fixture = tmp_path / "tagged-world.json"
    fixture.write_text(json.dumps({
        "schema": "opulse.world_v2_export/1", "world": "roads", "title": "Roads", "wave": 1,
        "open_kinds": ["object", "bridge"],
        "tags": {"domain": "math", "modalities": ["text", "image"], "star_kind": "bridge",
                 "reasoning": ["search"], "state": "stateless", "outcomes": "deterministic",
                 "visibility": "full", "agents": "1", "scale": "12 vertices",
                 "difficulty": "five rungs", "uses": ["evaluation"]},
        "story": [],
    }))
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      globalThis.document = {createElement(tag) {
        return {tag, children:[], setAttribute(key, value) {this[key] = value},
          appendChild(child) {this.children.push(child)}, textContent:''};
      }};
      const world = require(process.argv[2]);
      const chips = A2.worlds.fieldChips(world, ['domain', 'modalities', 'open_kinds']);
      const fullChips = A2.worlds.fieldChips(world);
      const matches = filters => catalog.filterWorlds([world], filters).length;
      console.log(JSON.stringify({chips:chips.children.map(child => child.textContent),
        all:fullChips.children.map(child => child.textContent),
        open:A2.worlds.openKinds(world), math:matches({domain:'math'}), image:matches({modalities:'image'}),
        bridge:matches({open_kinds:'bridge'}), kind:matches({kind:'bridge'}),
        mismatch:matches({open_kinds:'operation'}), pending:chips.children.some(child => child.textContent === 'tags pending')}));
    """, str(fixture))
    assert result == {"chips": ["domain: math", "modalities: text", "modalities: image",
                                 "open kinds: object", "open kinds: bridge"],
                      "all": ["domain: math", "modalities: text", "modalities: image",
                              "open kinds: object", "open kinds: bridge",
                              "star kind: bridge", "reasoning: search", "state: stateless",
                              "outcomes: deterministic", "visibility: full", "agents: 1",
                              "scale: 12 vertices", "difficulty: five rungs", "uses: evaluation"],
                      "open": ["object", "bridge"], "math": 1, "image": 1, "bridge": 1,
                      "kind": 1, "mismatch": 0, "pending": False}


def test_catalog_story_tokens_wrap_instead_of_clipping() -> None:
    css = (ROOT / "docs/assets/css/worlds-v2.css").read_text()
    assert ".w2-story { display: flex; align-items: center; flex-wrap: wrap;" in css
    assert ".w2-story .a2-tok { max-width: 100%; white-space: normal; overflow-wrap: anywhere;" in css


def test_tower_dependencies_preserve_given_kinds_and_definition_layers() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const roads = require(root + '/docs/assets/data/worlds_v2/roads.json');
      const cost = roads.story.find(entry => entry.name === 'cost');
      const best = roads.story.find(entry => entry.name === 'best');
      console.log(JSON.stringify({given:A2.worlds.dependencies(roads.story, cost, roads.decl).find(dep => dep.name === 'edge'),
        invented:A2.worlds.dependencies(roads.story, best, roads.decl).find(dep => dep.name === 'cost'),
        inventedLabel:A2.worlds.label,
        exportCall:A2.worlds.exportNotation({ascii:'?shortest{5}'}),
        unicodeCall:A2.worlds.exportNotation({ascii:'◉shortest⦅5⦆'}),
        givenKinds:A2.worlds.givenKinds(roads.decl)}));
    """)
    assert result["given"] == {"name": "edge", "kind": "operation", "invented": False}
    assert result["invented"] == {"name": "cost", "row": 2, "layer": 2,
                                  "kind": "operation", "invented": True}
    assert "inventedLabel" not in result
    assert result["exportCall"] == "?shortest{5}"
    assert result["unicodeCall"] is None
    assert result["givenKinds"]["Roads"] == "object"


def test_depth_export_names_have_kind_sigils_and_suppressed_traces_remain_visible() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const worlds = ['roads','action','pixels'].map(id => require(root + '/docs/assets/data/worlds_v2/' + id + '.json'));
      const names = worlds.flatMap(world => world.story.map(A2.worlds.identifier));
      const markers = worlds.flatMap(world => world.story.flatMap(entry => entry.examples.flatMap(example =>
        example.trace ? A2.worlds.traceLines(example.trace, [], 0).map(step => step.elided).filter(value => typeof value === 'string') : [])));
      const suppressed = {trace:{elided:'trace suppressed for large exact kernel run', children:[], steps:1750406}};
      console.log(JSON.stringify({names, markers, suppressedVisible:A2.worlds.traceLines(suppressed.trace, [], 0)[0].elided,
        suppressedExpandable:A2.worlds.hasTrace(suppressed)}));
    """)
    assert "@scan" in result["names"] and "?cut_certificate" in result["names"]
    assert all(marker.isascii() for marker in result["markers"])
    assert result["suppressedVisible"] == "trace suppressed for large exact kernel run"
    assert result["suppressedExpandable"] is False
    assert all(name.isascii() for name in result["names"])


def test_long_recorded_values_are_collapsible_without_losing_exact_text() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs, children) => ({tag, attrs, children});
      A2.expr = text => ({tag:'expr', text});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const long = 'Inputs: ' + 'a'.repeat(400);
      const short = 'Ok(1)';
      const hidden = A2.worlds.recordedValue('inputs', long, []);
      const visible = A2.worlds.recordedValue('outcome', short, []);
      console.log(JSON.stringify({tag:hidden.tag, caption:hidden.children[0].attrs.text,
        exact:hidden.children[1].text, shortTag:visible.tag, shortText:visible.text}));
    """)
    assert result == {"tag": "details", "caption": "Inspect recorded inputs (long value)",
                      "exact": "Inputs: " + "a" * 400, "shortTag": "expr", "shortText": "Ok(1)"}


def test_catalogue_notices_follow_depth_exports() -> None:
    source = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    catalog = (ROOT / "docs/worlds/index.md").read_text()
    assert 'var junctions = graph && graph.f && graph.f[0] && graph.f[0].f;' in source
    assert 'var roads = graph && graph.f && graph.f[1] && graph.f[1].f;' in source
    assert 'A2.worlds.displayIdentifier(entry)' in source
    assert 'A2.worlds.identifier(last)' in source
    assert 'fetch(base + "computer.json")' in source
    assert 'if (!exports.some(function (entry) { return entry.world === "computer"; })) exports.push(computer);' in source
    assert 'entry.tags.modalities = entry.design.modalities;' not in source
    assert "Export: three-cell corridor." in catalog
    assert "The 277 closures of size at most two are a Metro run, outside the recorded checked scope." in source


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_combinator_export_declarations_and_computer_cases_are_renderable() -> None:
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const computer = require(root + '/docs/assets/data/worlds_v2/computer.json');
      const roads = require(root + '/docs/assets/data/worlds_v2/roads.json');
      const combOnly = require(root + '/docs/assets/data/worlds_v2/comb_only.json');
      console.log(JSON.stringify({computerRows:computer.story.length,
        computerCases:computer.story.reduce((sum, row) => sum + row.examples.length, 0),
        computerDecl:A2.worlds.exportNotation(computer.story[0]),
        roadsDecl:A2.worlds.exportNotation(roads.story.find(row => row.kind === 'combinator')),
        mapDecl:A2.worlds.exportNotation(combOnly.story.find(row => row.name === 'map'))}));
    """)
    assert result["computerRows"] == 11
    assert result["computerCases"] >= 11
    assert result["computerDecl"].startswith("comb @while_b[")
    # roads' @explore has no printable source; its old placeholder body must not come back.
    assert result["roadsDecl"] is None
    assert result["mapDecl"].startswith("comb @map[")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_differing_declaration_and_computed_layers_are_both_explicit() -> None:
    computer = json.loads((ROOT / "docs/assets/data/worlds_v2/computer.json").read_text())
    row = next(entry for entry in computer["story"] if entry["name"] == "?dot_wrap")
    assert row["layer"] != row["def_layer"]
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      const computer = require(root + '/docs/assets/data/worlds_v2/computer.json');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children:Array.isArray(children) ? children : [children],
        style:{setProperty() {}}, appendChild(child) {this.children.push(child)}});
      A2.expr = text => A2.el('expr', {text});
      A2.value = input => A2.el('value', {input});
      A2.token = (text, options) => A2.el('token', {text, options});
      A2.badge = name => Object.assign(A2.el('badge', {text:name}), {setAttribute() {}});
      A2.register = () => {};
      require(root + '/docs/assets/js/atoms2/tower.js');
      const row = computer.story.find(entry => entry.name === '?dot_wrap');
      const card = A2.worlds.entryCard(row, computer.story, 'computer.json', computer.decl);
      console.log(JSON.stringify(card.children.map(child => child.attrs?.text).filter(Boolean)));
    """)
    assert f"Declared L{row['layer']}, computed layer {row['def_layer']}" in result


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_suppressed_trace_has_no_trace_badge_and_each_case_has_purpose() -> None:
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const roads = require(root + '/docs/assets/data/worlds_v2/roads.json');
      const grammar = require(root + '/docs/assets/data/worlds_v2/grammar.json');
      const cut = roads.story.find(entry => entry.name === 'cut_certificate');
      const invert = grammar.story.find(entry => entry.name === 'invert_gap');
      console.log(JSON.stringify({cutTrace:A2.worlds.hasTrace(cut.examples[0]),
        recordedTrace:A2.worlds.hasTrace(roads.story[0].examples[0]),
        cutPurpose:A2.worlds.casePurpose(cut, cut.examples[0]),
        invertPurpose:A2.worlds.casePurpose(invert, invert.examples[0])}));
    """)
    assert result["cutTrace"] is True
    assert result["recordedTrace"] is True
    assert "no checked 0.5 core trace" in result["cutPurpose"]
    assert "seven-token word" in result["invertPurpose"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_dependency_inspector_separates_referenced_names_from_recorded_edges() -> None:
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const world = require(root + '/docs/assets/data/worlds_v2/comb_only.json');
      const row = world.story.find(entry => entry.name === 'map');
      console.log(JSON.stringify({recorded:A2.worlds.dependencies(world.story, row, world.decl),
        referenced:A2.worlds.referencedDependencies(world.story, row, world.decl)}));
    """)
    assert {entry["name"] for entry in result["recorded"]} == {"append", "empty", "head", "length", "tail"}
    assert all(entry["kind"] == "operation" and entry["invented"] is False for entry in result["recorded"])
    assert result["referenced"] == [{"name": "List", "kind": "object", "invented": False}]


def test_catalog_search_includes_exported_and_designed_tower_definitions() -> None:
    result = run_node("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const roads = require(root + '/docs/assets/data/worlds_v2/roads.json');
      roads.title = 'Roads'; roads.world = 'roads'; roads.design = {
        tower:[{name:'imagined_cut', decl:'obj ImaginedCut = Graph<> L4'}]};
      console.log(JSON.stringify({exported:catalog.filterWorlds([roads], {q:'shortest'}).length,
        designed:catalog.filterWorlds([roads], {q:'ImaginedCut'}).length,
        absent:catalog.filterWorlds([roads], {q:'unrelated_phrase'}).length}));
    """)
    assert result == {"exported": 1, "designed": 1, "absent": 0}


def test_world_next_actions_and_legacy_aliases_are_scoped() -> None:
    script = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    legacy = (ROOT / "docs/assets/js/worlds/legacy-ui.js").read_text()
    assert '["integer", "computer", "roads"].includes(id)' in script
    assert 'id === "roads" ? path(mount, "play/challenge/")' in script
    assert '"play/?world=integer"' in script
    assert '"play/?world=computer"' in script
    assert '"Inspect exported cases"' in script
    assert '"Create a world like this"' in script
    assert '"#definition-workshop"' in script
    assert 'text: "Create a world"' not in script
    assert 'origin: "invented", layer: operator.layer' not in legacy
    assert '"0 confirmed executable on the current core"' not in script
    assert "w2-contract-panel" in script


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_inputs_collapse_into_disclosure_when_a_summary_is_shown():
    result = run_js("""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const node = {tag, attrs, children:[], style:{setProperty() {}},
          appendChild(child) {this.children.push(child)}};
        for (const child of (Array.isArray(children) ? children : [children])) if (child) node.appendChild(child);
        return node;
      }
      Object.assign(A2, {el, token:(name) => el('token', {name}), expr:(content) => el('expr', {content}),
        value:(content) => el('value', {content}),
        badge:() => Object.assign(el('badge'), {setAttribute() {}}), register() {}});
      require(root + '/docs/assets/js/atoms2/tower.js');
      const flatten = node => [node, ...(node.children || []).flatMap(flatten)];
      const step = require(root + '/docs/assets/data/worlds_v2/action.json').story
        .find(entry => entry.name === 'safe_step');
      const card = A2.worlds.entryCard(step, [step], '', {}, 'action');
      const plain = {name:'f', kind:'operation', layer:1,
        examples:[{ascii:'f(1)', inputs:[{t:'int', v:1}], outcome:{ok:{t:'int', v:2}}}]};
      const plainCard = A2.worlds.entryCard(plain, [plain], '', {}, 'integer');
      const disclosed = card => flatten(card).filter(node => node.tag === 'details' &&
        node.children.some(child => child.attrs && child.attrs.text === 'Inspect recorded inputs'))
        .map(node => node.children[1].attrs.class);
      console.log(JSON.stringify({summary: disclosed(card), plain: disclosed(plainCard)}));
    """)
    assert result["summary"] and set(result["summary"]) == {"w2-input-values"}
    assert result["plain"] == []
