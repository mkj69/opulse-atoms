"""Regression checks for Play interaction controls and guided task navigation."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "docs/assets/js/atoms2"
NODE = shutil.which("node")


def test_sample_preset_reveals_seed_and_method_label_stays_accurate():
    source = (JS / "define.js").read_text()
    assert 'value: "sampled", text: "Seeded sample"' in source
    assert 'seedField.hidden = method.value !== "sampled"; seed.disabled = seedField.hidden;' in source
    assert 'method.value = choice.sampled ? "sampled" : "exhaustive"; updateSeed();' in source


def test_kind_tab_panel_contains_editor_and_lifecycle():
    source = (JS / "define.js").read_text()
    assert 'columns.append(editor, resultPane);' in source
    assert 'role: "tabpanel", tabindex: "0" }, columns)' in source
    assert 'section.append(tabs, tabPanel, shelves, usage)' in source
    assert 'tabPanel.setAttribute("aria-labelledby", "a2-define-tab-" + kind)' in source


def test_fuel_change_waits_for_explicit_run():
    source = (JS / "lab-computer.js").read_text()
    assert 'fuel.addEventListener("input", function () {' in source
    assert 'fuel.addEventListener("change"' not in source
    assert 'run.addEventListener("click", function () {\n      runMachine(false, false);' in source


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_guided_route_and_angle_ladder_selection_stay_distinct():
    script = r"""
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.className = ''; this.dataset = {}; this.listeners = {}; this.attrs = {}; this.textContent = '';
    this.classList = {toggle: (name, enabled) => { this.className = this.className.split(' ').filter(part => part !== name).concat(enabled ? [name] : []).join(' '); }};
  }
  appendChild(element) { if (element.parentNode) element.parentNode.children = element.parentNode.children.filter(child => child !== element); this.children.push(element); element.parentNode = this; return element; }
  prepend(element) { this.children.unshift(element); }
  replaceChildren(...elements) { this.children.forEach(element => element.parentNode = null); this.children = []; elements.forEach(element => this.appendChild(element)); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(key, handler) { this.listeners[key] = handler; }
  click() { this.listeners.click(); }
  focus() { document.activeElement = this; }
  scrollIntoView() {}
  querySelectorAll(selector) {
    const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return descendants;
    if (selector === 'button' || selector === 'h2') return descendants.filter(child => child.tagName === selector);
    return descendants.filter(child => child.className.split(' ').includes(selector.slice(1)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
globalThis.document = {readyState: 'loading', createElement: tag => new Element(tag), addEventListener() {}};
globalThis.A2 = {badge: () => new Element('span'), token: () => new Element('span'), kindBadge: () => new Element('span'), expr: () => new Element('code'), reducedMotion: () => true};
const catalogue = require(process.argv[1]);
const {render} = require(process.argv[2]);
const host = new Element('div');
render(host, catalogue);
const route = host.querySelector('.ladder-route');
const controls = route.querySelectorAll('.ladder-route-button');
const tabs = host.querySelectorAll('.ladder-tab');
const items = host.querySelectorAll('.ladder-item');
const progress = host.querySelector('.ladder-route-progress');
const next = controls[controls.length - 1];
assert.equal(controls[0].getAttribute('aria-current'), 'true');
assert(items.every(item => item.getAttribute('aria-current') === 'false'));
assert(tabs.every(tab => tab.getAttribute('aria-pressed') === 'false'));
assert(progress.textContent.includes('step 1 of 6'));
assert.equal(next.hidden, false);
assert.equal(host.querySelector('.ladder-detail').parentNode, route);
assert(host.querySelector('.ladder-grid').className.includes('is-guided'));
next.click();
assert.equal(controls[1].getAttribute('aria-current'), 'true');
assert(progress.textContent.includes('step 2 of 6'));
items[1].click();
assert.equal(items[1].getAttribute('aria-current'), 'true');
assert(controls.slice(0, -1).every(control => control.getAttribute('aria-current') === 'false'));
assert.equal(next.hidden, true);
assert.equal(tabs[0].getAttribute('aria-pressed'), 'true');
assert.equal(host.querySelector('.ladder-detail').parentNode.className, 'ladder-grid');
controls[5].click();
assert.equal(host.querySelector('.ladder-detail').parentNode, route);
assert.equal(next.hidden, true);
assert.equal(controls[5].getAttribute('aria-current'), 'true');
tabs[1].click();
assert.equal(next.hidden, true);
assert.equal(tabs[1].getAttribute('aria-pressed'), 'true');
assert(host.querySelectorAll('.ladder-item').some(item => item.getAttribute('aria-current') === 'true'));
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "docs/assets/data/challenge/v2.json"), str(JS / "ladders.js")],
        capture_output=True, text=True,
    check=False)
    assert result.returncode == 0, result.stderr
