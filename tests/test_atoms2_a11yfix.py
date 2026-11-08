"""Accessibility regressions for the atoms-v2 interactive widgets."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
ROADS = ROOT / "docs/assets/js/atoms2/roads.js"
CATALOG = ROOT / "docs/assets/js/worlds/catalog-ui.js"
COMPUTER = ROOT / "docs/assets/js/atoms2/lab-computer.js"


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_focus_and_status_behaviour_in_node():
    script = r"""
const assert = require('node:assert/strict');
const roads = require(process.argv[1]);
const catalog = require(process.argv[2]);
global.A2 = {};
const computer = require(process.argv[3]);
const fakeDocument = {activeElement: null};
const path = {
  ownerDocument: fakeDocument, buttons: [],
  contains(button) { return this.buttons.includes(button); },
  replaceChildren() { this.buttons = []; fakeDocument.activeElement = null; },
  querySelectorAll() { return this.buttons; }
};
function button(name) {
  return {dataset: {name}, closest() { return this; }, focus() { fakeDocument.activeElement = this; }};
}
const original = button('cost');
path.buttons = [original];
original.focus();
roads.redrawPathKeepingFocus(path, ['cost', 'best'], name => path.buttons.push(button(name)));
assert.equal(fakeDocument.activeElement, path.buttons[0]);
assert.notEqual(fakeDocument.activeElement, original);
const cards = {
  links: [{focus() { throw Error('focused old link'); }}],
  querySelectorAll() { return this.links; }
};
let focused = false;
catalog.expandWorlds(cards, () => { cards.links = [cards.links[0], {focus() { focused = true; }}]; });
assert.equal(focused, true);
const status = {textContent: ''};
computer.announcePlayback(status, 'start', 'Run started');
computer.announcePlayback(status, 'tick', 'Step 25');
assert.equal(status.textContent, 'Run started');
computer.announcePlayback(status, 'end', 'Run complete');
assert.equal(status.textContent, 'Run complete');
const listeners = {};
const field = {addEventListener(event, callback) { listeners[event] = callback; }};
let synced = 0;
const changed = roads.bindWitness(field, field, status, () => synced++);
changed(false);
assert.equal(status.textContent, 'Run complete');
changed(true);
assert.equal(status.textContent, 'Answer changed. Check again.');
assert.equal(synced, 2);
"""
    subprocess.run([NODE, "-e", script, str(ROADS), str(CATALOG), str(COMPUTER)], check=True)


def test_live_regions_and_reduced_motion_keep_steps_available():
    roads = ROADS.read_text()
    computer = COMPUTER.read_text()
    catalog = CATALOG.read_text()
    assert 'data-roads-step aria-live' not in (ROOT / "docs/index.md").read_text()
    assert 'play.click()' not in roads
    assert 'index = steps.length - 1' not in roads
    assert 'if (reducedMotion) play.hidden = true' in roads
    assert '.roads-card [data-roads-play][hidden] { display: none; }' in (ROOT / "docs/assets/css/atoms2-roads.css").read_text()
    assert 'controls.addEventListener("keydown"' not in roads
    assert 'nodeButtons.get(id).setAttribute("aria-pressed", String(route.includes(id)))' in roads
    assert 'changed(false); announceMap();' in roads
    assert '"aria-live": "polite"' not in computer
    assert computer.count('role: "status"') == 1
    assert '"aria-live": "polite"' not in catalog
    assert catalog.count('role: "status"') == 2
    assert 'tabs.setAttribute("role", "group")' in (ROOT / "docs/assets/js/atoms2/ladders.js").read_text()
    definition = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert 'Store browser preview in session' in definition
    assert 'evidence.method + "; scope: " + evidence.scope.domain' in definition
    for page in ("worlds/index.md", "worlds/action/index.md", "worlds/roads/index.md"):
        assert 'aria-live="polite"' not in (ROOT / "docs" / page).read_text()
    assert 'display: none' not in re.search(r"\.a2-learn-overview thead \{([^}]+)\}",
                                           (ROOT / "docs/assets/css/learn.css").read_text()).group(1)


def _rgb(color):
    return tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def _luminance(color):
    red, green, blue = _rgb(color)
    channels = tuple(channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
                     for channel in (red, green, blue))
    return sum(channel * weight for channel, weight in zip(channels, (.2126, .7152, .0722)))


def _contrast(front, back):
    light, dark = sorted((_luminance(front), _luminance(back)), reverse=True)
    return (light + .05) / (dark + .05)


def _mix(front, back, proportion):
    return "#" + "".join(f"{round((front_channel * proportion + back_channel * (1 - proportion)) * 255):02x}"
                         for front_channel, back_channel in zip(_rgb(front), _rgb(back)))


def test_composited_value_contrast_at_least_aa():
    css = (ROOT / "docs/assets/css/atoms2.css").read_text()
    custom = (ROOT / "docs/assets/css/custom.css").read_text()
    scheme = re.search(r'\[data-md-color-scheme="default"\] \{([^}]+)\}', css).group(1)
    color = lambda source, variable: re.search(rf'{re.escape(variable)}:\s*(#[0-9a-f]{{6}})', source).group(1)
    object_color = color(scheme, "--a2-object")
    light = re.search(r'\[data-md-color-scheme="default"\] \{([^}]+)\}', custom).group(1)
    cyan = color(light, "--op-cyan")
    tag_color = re.search(r'\[data-md-color-scheme="default"\] \.a2-v-tag \{ color: (#[0-9a-f]{6})', css).group(1)
    result_color = re.search(r'\[data-md-color-scheme="default"\] \.a2-v-result \{ color: (#[0-9a-f]{6})', css).group(1)
    assert _contrast(tag_color, _mix(object_color, "#ffffff", .10)) >= 4.5
    assert _contrast(result_color, _mix(cyan, "#ffffff", .22)) >= 4.5
    dark = re.search(r'\[data-md-color-scheme="slate"\] \{([^}]+)\}', css).group(1)
    dark_custom = next(block for block in re.findall(r':root \{([^}]+)\}', custom) if '--op-cyan:' in block)
    dark_panel = _mix("#ffffff", "#0f172a", .035)
    assert _contrast(color(dark, "--a2-object"), _mix(color(dark, "--a2-object"), dark_panel, .14)) >= 4.5
    assert _contrast(color(dark_custom, "--op-cyan"), _mix(color(dark_custom, "--op-cyan"), dark_panel, .22)) >= 4.5
