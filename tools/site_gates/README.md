# Site release gates

Build the English site first. Run the commands from the repository root with
Chrome and Node available on `PATH`, plus Python with the project dependencies
and `sitecheck` installed (or activate the relevant virtual environment).
A failing command blocks release; do not suppress a finding without
investigating it. No Chrome run is claimed by the static tests.

Before building, run the regeneration release gate from the repository root:

```sh
PYTHONPATH=src python tools/site_gates/regen_check.py
```

It runs the notation-v3 stamp, UI trace, walk, tower, roads, grammar, parse-status and research-bundle
exporters with `--check`. It never rewrites artifacts. A failure names the exporter
and the stale file; regenerate with the corresponding `tools/*.py` script, then
check the resulting diff. A world build failure instead names the failing world
and must be fixed in that world's code or the core before publishing.

```sh
PYTHONPATH=src python -m mkdocs build -f mkdocs.yml -d /tmp/opulse-gates-site
SITE=/tmp/opulse-gates-site
CONFIG=tools/site_gates/sitecheck.toml
sitecheck --config "$CONFIG" smoke "$SITE" --output /tmp/opulse-gates-smoke
sitecheck --config "$CONFIG" navwalk "$SITE" --output /tmp/opulse-gates-nav
sitecheck --config "$CONFIG" lang "$SITE" --include '/*' --output /tmp/opulse-gates-lang
python3 tools/site_gates/generate_challenge_walk.py
for script in tools/site_gates/walk_*.json build/site_gates/walk_*.json; do
  sitecheck --config "$CONFIG" walk "$SITE" --script "$script" --output "/tmp/opulse-gates-$(basename "$script" .json)" || exit 1
done
```

The correct-answer challenge walk is generated into ignored `build/site_gates/`
from the public roads graph and checker each time. Never commit that walk or
copy its filled fields into the tracked walks or tests. The tracked wrong-answer
walk still verifies rejection without revealing the winning witness.

The navwalk config limits discovery to every published page in the `mkdocs.yml`
navigation. The language command overrides that limit to include every English
page, including world details. Review each output's `report.json` after the run.
Sitecheck's navwalk accepts one widget selector at a time. Check the flagship
roots in isolated invocations (the optional configuration map records them):

```sh
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/' --widget-root '[data-roads-home]' --output /tmp/opulse-gates-widget-home
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/play/' --widget-root '[data-a2="computerLab"]' --output /tmp/opulse-gates-widget-lab
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/play/' --widget-root '[data-a2="define"]' --output /tmp/opulse-gates-widget-workshop
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/play/challenge/' --widget-root '[data-roads-challenge]' --output /tmp/opulse-gates-widget-challenge
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/learn/checks/' --widget-root '[data-a2-learn="checks"]' --output /tmp/opulse-gates-widget-checks
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/worlds/' --widget-root '[data-worlds-v2]' --output /tmp/opulse-gates-widget-worlds
sitecheck --config "$CONFIG" navwalk "$SITE" --include '/reference/' --widget-root '#a2-reference-modes' --output /tmp/opulse-gates-widget-reference
```

`navwalk` attempts to click every discovered URL from Home, not via its parent
tab. Some child pages are not directly linked on Home; report their
`nav_link_missing` findings to the shell owner rather than treating them as
passes. The walk scripts open those child pages directly for interaction checks.

Run `pytest -q tests/test_site_gates_static.py` before any browser run. These
tests catch stale source labels, selectors, and nav coverage, not rendered UI
or JavaScript errors. The walks require the JSON fixtures and their backing
page scripts to load; inspect failures instead of accepting partial passes.
The challenge walks fill both fields to exercise input handlers, then reopen
with matching query parameters and `check=1` to submit. Sitecheck's
`click_text` assumes controls have `innerText`, but the accessible SVG road
buttons ahead of the form do not. A direct text click fails in sitecheck
before reaching the submit button.

Keyboard focus gate (DevTools key events in Chrome; sitecheck walks cannot press keys).
Run it with the Python that has `sitecheck` installed; every line must start with PASS:

```sh
python tools/site_gates/keyboard_check.py "$SITE"
```

Notation v3 rendered round-trip gate (Chrome required):

```sh
PYTHONPATH=src python tools/site_gates/n3_roundtrip.py "$SITE" --output /tmp/opulse-n3-roundtrip.json
```

This opens every MkDocs navigation page and world detail, checks all rendered
`.n3` pairs, rejects `.n3-missing`, disallowed visible glyphs, CJK, and
`[object Object]`. It also rejects unindexed non-given marks, legacy `::`
constructors, bare-name chips outside legends, and rendered right-superscript
chip content. Review the JSON report; any finding blocks release.

Notation v3 rendered contrast gate (Chrome required):

```sh
PYTHONPATH=src python tools/site_gates/n3_contrast.py "$SITE" --output /tmp/opulse-n3-contrast.json
```

It checks every rendered notation glyph and direct formula text at 1440 and
390 pixels in both Material colour schemes, opening all `<details>` without
clicking data-changing controls. The JSON records counts and worst failures
per page, width, and scheme; any contrast below WCAG 4.5:1 (3:1 for large
text) blocks release. Run `pytest -q tests/test_n3_contrast_gate.py` for
the browser-independent contrast calculations.
