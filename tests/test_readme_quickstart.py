"""The README quick start runs as written and prints the output it shows."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _quick_start():
    section = README.split("## Quick start", 1)[1].split("\n## ", 1)[0]
    scripts = re.findall(r"```bash\npython - <<'PY'\n(.*?)\nPY\n```", section, re.S)
    outputs = re.findall(r"```text\n(.*?)```", section, re.S)
    return scripts, outputs


def _run(script):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run([sys.executable, "-"], input=script, text=True, capture_output=True,
                          cwd=ROOT, env=env, check=True, timeout=300).stdout


def test_readme_quick_start_prints_the_shown_output():
    scripts, outputs = _quick_start()
    assert len(scripts) == 2 and len(outputs) == 1
    assert _run(scripts[0]) == outputs[0]


def test_readme_world_listing_runs():
    scripts, _ = _quick_start()
    lines = _run(scripts[1]).splitlines()
    assert re.fullmatch(r"\d+ worlds: [a-z_]+(, [a-z_]+)+", lines[0])
    count = int(lines[0].split()[0])
    assert f"{count} atoms-v2 worlds in the world index" in README
    assert len(lines) == 5


def test_readme_is_plain_english():
    assert "—" not in README and "–" not in README
    assert not re.search("[㐀-鿿豈-﫿]", README)
    assert "pip install -e '.[dev,site]'" in README


def test_readme_world_count_matches_the_catalog_page():
    # docs/assets/js/worlds/catalog-ui.js shows every index entry plus computer.json when the
    # index does not list computer.
    data = ROOT / "docs/assets/data/worlds_v2"
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    names = [entry["world"] for entry in index["worlds"]]
    computer = json.loads((data / "computer.json").read_text(encoding="utf-8"))
    assert computer["schema"] == "opulse.world_v2_export/1" and computer["world"] == "computer"
    shown = len(names) + (0 if "computer" in names else 1)
    assert f"The world catalog has {shown} worlds" in " ".join(README.split())
    declared = {path.name.split("@")[0] for path in (ROOT / "worlds/decl/v2").glob("*@*.json")}
    assert len(declared) == shown
