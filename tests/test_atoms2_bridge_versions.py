"""Bridge evidence must not be presented as checked on another export version."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_published_bridge_hashes_are_compared_before_display():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = r"""
      const root = process.argv[1];
      const bridges = require(root + '/docs/assets/data/worlds_v2/bridges/bridges.json').story;
      const hashes = Object.fromEntries(['rhythm', 'pixels', 'integer'].map(name =>
        [name, require(root + '/docs/assets/data/worlds_v2/' + name + '.json').world_hash]));
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs,
        children: Array.isArray(children) ? children : [children],
        appendChild(child) {this.children.push(child)}});
      A2.token = name => A2.el('token', {text:name});
      A2.expr = value => A2.el('code', {text:value});
      A2.badge = status => A2.el('badge', {text:status});
      A2.worlds = {ascii: value => value, outcomeNotation: value => JSON.stringify(value)};
      global.location = {href:'https://example.test/worlds/rhythm/'};
      const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const panel = catalog.bridgePanel({dataset:{root:'https://example.test/' }},
        {world:'rhythm', bridges, worldExports:hashes, parseStatus:{entries:{'bridge/beat_row':true}}});
      const nodes = node => [node, ...(node.children || []).filter(Boolean).flatMap(nodes)];
      console.log(JSON.stringify({mismatch:catalog.bridgeVersionMismatch(bridges[0], hashes),
        integer:catalog.bridgeVersionMismatch(bridges[1], hashes),
        labels:nodes(panel).map(node => node.attrs && node.attrs.text).filter(Boolean)}));
    """
    result = subprocess.run(["node", "-e", script, str(ROOT)], text=True, capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert len(data["mismatch"]) == 2
    assert {item["world"] for item in data["mismatch"]} == {"rhythm@1", "pixels@1"}
    assert "evidence for an earlier world version" in data["labels"]
    assert "design" in data["labels"]
    assert "checked" not in data["labels"]
    for item in data["mismatch"]:
        assert item["evidence"] != item["published"]
        assert item["evidence"] in data["labels"]
        assert item["published"] in data["labels"]
    assert len(data["integer"]) == 1
    assert data["integer"][0]["world"] == "integer@2"
