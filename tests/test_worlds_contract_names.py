"""Layer-0 contract chips name every given definition (review round 25 G1)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_contract_chips_never_render_object_placeholders():
    script = r"""
      const fs = require('fs');
      const base = process.argv[1];
      const A2 = require(base + '/docs/assets/js/atoms2/kit.js');
      require(base + '/docs/assets/js/atoms2/tower.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, text: attrs.text,
        children: (Array.isArray(children) ? children : [children]).filter(Boolean),
        appendChild(child) {this.children.push(child)}, setAttribute() {}});
      A2.token = (text, options) => A2.el('token', {text: String(text), kind: options && options.kind});
      A2.badge = name => A2.el('badge', {text: String(name)});
      A2.expr = text => A2.el('code', {text: String(text)});
      const {contract} = require(base + '/docs/assets/js/worlds/catalog-ui.js');
      function tokens(node) {
        return [...(node.tag === 'token' ? [[node.attrs.kind, node.text]] : []),
                ...(node.children || []).flatMap(tokens)];
      }
      function strings(node) {
        return [node.text, ...(node.children || []).flatMap(strings)].filter(value => value != null);
      }
      const out = {};
      for (const name of fs.readdirSync(base + '/docs/assets/data/worlds_v2')) {
        if (!name.endsWith('.json') || name === 'index.json') continue;
        const world = require(base + '/docs/assets/data/worlds_v2/' + name);
        if (!world.decl) continue;
        const section = contract({}, world);
        const library = (world.decl.combinators && world.decl.combinators.library) || [];
        out[name] = {text: strings(section).join(' '),
                     combinators: tokens(section).filter(([kind]) => kind === 'combinator').map(([, text]) => text),
                     expected: library.map(item => typeof item === 'string' ? item : item.name)};
      }
      console.log(JSON.stringify(out));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT)], capture_output=True, text=True, check=True)
    worlds = json.loads(result.stdout)
    assert len(worlds) >= 21
    object_library = [name for name, world in worlds.items() if world["expected"]]
    assert object_library
    for name, world in worlds.items():
        assert "[object Object]" not in world["text"], name
        assert "undefined" not in world["text"], name
        assert world["combinators"] == world["expected"], name
