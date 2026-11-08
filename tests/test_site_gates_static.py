import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

try:  # Python 3.11+ ships the TOML reader as tomllib.
    import tomllib as tomli
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli
from mkdocs.config import load_config

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "tools/site_gates"
CONFIG = tomli.loads((GATES / "sitecheck.toml").read_text(encoding="utf-8"))
WALKS = sorted(GATES.glob("walk_*.json"))


def page_source(url):
    page = ROOT / "docs" / published_urls()[url]
    assert page.is_file(), url
    markdown = page.read_text(encoding="utf-8")
    javascript = [ROOT / "docs/assets/js/atoms2/kit.js"]
    for path in re.findall(r'<script\s+[^>]*src="([^"]+)"', markdown):
        from urllib.parse import urljoin, urlsplit

        asset = ROOT / "docs" / urlsplit(urljoin(url, path)).path.lstrip("/")
        assert asset.is_file(), (url, path)
        javascript.append(asset)
    return markdown + "\n" + "\n".join(file.read_text(encoding="utf-8") for file in javascript)


def published_urls():
    nav = load_config(str(ROOT / "mkdocs.yml"))["nav"]

    def leaves(items):
        for entry in items:
            for value in entry.values():
                if isinstance(value, list):
                    yield from leaves(value)
                else:
                    path = value.removesuffix("index.md") if value.endswith("index.md") else value.removesuffix(".md")
                    yield ("/" + path).rstrip("/") + "/", value

    return dict(leaves(nav))


@pytest.mark.parametrize("walk", WALKS, ids=lambda path: path.stem)
def test_walk_labels_exist_in_page_or_loaded_script(walk):
    script = json.loads(walk.read_text(encoding="utf-8"))
    assert len(script["urls"]) == 1
    target = script["pages"][script["urls"][0]]
    source = page_source(target)
    for step in script["steps"]:
        action, text = next(iter(step.items()))
        if action == "wait":
            text = text["text"] if isinstance(text, dict) else None
        if action not in ("click_text", "assert_text", "wait") or not text:
            continue
        if text in ("21 shown /", "0 shown /"):
            count = len(json.loads((ROOT / "docs/assets/data/worlds_v2/index.json").read_text())["worlds"]) + 1
            assert "matches.length + \" shown / \"" in source
            assert text == f"{count} shown /" or text == "0 shown /"
        elif text in ("Hide fixpoint kernel trace", "Explore fixpoint kernel trace"):
            assert '"Hide "' in source and '"Explore "' in source
            assert '"fixpoint"' in source and '" kernel trace"' in source
        elif text == "All members of a declared finite domain, if every case was run. Outside that domain, no claim.":
            assert text in (ROOT / "docs/assets/data/atoms2/checks.json").read_text(encoding="utf-8")
        else:
            assert text in source, (walk.name, target, action, text)


@pytest.mark.parametrize("walk", WALKS, ids=lambda path: path.stem)
def test_walk_fill_selectors_match_page_or_script(walk):
    script = json.loads(walk.read_text(encoding="utf-8"))
    source = page_source(script["pages"][script["urls"][0]])
    for step in script["steps"]:
        if "fill" not in step:
            continue
        selector = step["fill"]["selector"]
        for attribute, value in re.findall(r"\[([\w-]+)=['\"]([^'\"]+)['\"]\]", selector):
            assert any(text in source for text in (f'{attribute}="{value}"', f"{attribute}='{value}'",
                                                 f'"{attribute}": "{value}"')), selector


def test_all_published_nav_pages_are_in_navwalk_discovery():
    urls = set(published_urls())
    assert len(urls) >= 17
    assert urls == set(CONFIG["include"])
    assert CONFIG["sitemap"] and CONFIG["limit"] >= len(urls)
    assert ".md-tabs__link" in CONFIG["nav_selector"]
    assert ".md-nav__link" in CONFIG["nav_selector"]
    for url in urls:
        page_source(url)


def test_every_english_page_is_covered_by_rendered_language_rule():
    assert any(rule["page"] == "*" and "cjk" in rule["scripts"] and not rule["allow"]
               for rule in CONFIG["lang_rules"])
    assert "--include '/*'" in (GATES / "README.md").read_text(encoding="utf-8")


def test_rendered_notation_roundtrip_gate_documented():
    assert "tools/site_gates/n3_roundtrip.py" in (GATES / "README.md").read_text(encoding="utf-8")


def test_flagship_widget_roots_are_documented_and_exist():
    roots = CONFIG["widget_roots"]
    for url, selector in roots.items():
        target = "/play/" if url == "workshop" else url
        source = page_source(target)
        if selector.startswith("#"):
            assert f'id="{selector[1:]}"' in source
        else:
            attribute, value = re.fullmatch(r"\[([\w-]+)='([^']+)'\]", selector).groups() if "'" in selector else (selector[1:-1], None)
            assert f'{attribute}="{value}"' in source if value else attribute in source
    assert set(roots) == {"/", "/play/", "workshop", "/play/challenge/", "/learn/checks/",
                          "/worlds/", "/reference/"}


@pytest.mark.parametrize("result", ["correct", "wrong"])
def test_challenge_walk_submits_filled_witness_without_svg_text_click(result, tmp_path):
    if result == "correct":
        if shutil.which("node") is None:
            pytest.skip("node is not installed (the challenge walk generator runs the page checker)")
        from tools.site_gates.generate_challenge_walk import generate_walk

        output = generate_walk(tmp_path / "walk_challenge_correct.json")
    else:
        output = GATES / "walk_challenge_wrong.json"
    walk = json.loads(output.read_text(encoding="utf-8"))
    steps = walk["steps"]
    assert not any("click_text" in step for step in steps)
    filled = {step["fill"]["selector"].split("name='")[1].split("'")[0]: step["fill"]["value"]
              for step in steps if "fill" in step}
    opened = [step["open"] for step in steps if "open" in step]
    assert len(opened) == 1
    url = urlsplit(opened[0])
    assert url.path == "/play/challenge/"
    params = parse_qs(url.query, keep_blank_values=True)

    def entries(value):
        return [entry for entry in re.split(r"[\s,]+", value.upper()) if entry]

    assert {name: entries(params[name][0]) for name in ("closed", "route")} == {
        name: entries(value) for name, value in filled.items()
    }
    assert params["check"] == ["1"]
    assert 'if (params.get("check") === "1") challenge.querySelector("form").requestSubmit();' in page_source(url.path)


def test_no_tracked_ui_file_contains_challenge_witness(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed (the challenge walk generator runs the page checker)")
    from tools.site_gates.generate_challenge_walk import generate_walk

    walk = json.loads(generate_walk(tmp_path / "correct.json").read_text(encoding="utf-8"))
    values = {step["fill"]["selector"].split("name='")[1].split("'")[0]: step["fill"]["value"]
              for step in walk["steps"] if "fill" in step}
    route = [item.strip() for item in values["route"].split(",")]
    pattern = re.compile(r"[\"']?\s*,\s*[\"']?".join(map(re.escape, route)))
    url_route = quote(",".join(route), safe="")
    tracked = subprocess.run(["git", "ls-files", "-z", "--", "tests", "tools/site_gates",
                              "docs/assets/js", "docs/assets/css", "docs/index.md", "docs/learn",
                              "docs/play", "docs/research", "docs/build", "docs/reference"],
                             cwd=ROOT, check=True, capture_output=True).stdout.decode().split("\0")
    for name in filter(None, tracked):
        path = ROOT / name
        if not path.is_file() or path.suffix not in {".py", ".js", ".json", ".md"}:
            continue
        content = path.read_text(encoding="utf-8")
        assert not pattern.search(content), name
        assert url_route not in content, name


def test_home_plays_on_request_then_replays_after_the_answer():
    # Home does not autoplay (accessibility review rv8); the walk starts recorded playback.
    steps = json.loads((GATES / "walk_home.json").read_text(encoding="utf-8"))["steps"]
    assert steps[:5] == [{"wait": {"text": "Play recorded steps", "timeout": 15}},
                         {"click_text": "Play recorded steps"},
                         {"wait": {"text": "Answer: false", "timeout": 15}},
                         {"click_text": "Replay recorded steps"},
                         {"wait": {"text": "Answer: false", "timeout": 15}}]


def test_workshop_selects_reference_before_expectation_of_previewed_result():
    steps = json.loads((GATES / "walk_workshop.json").read_text(encoding="utf-8"))["steps"]
    assert steps.index({"click_text": "Operation"}) < steps.index({"click_text": "Example"})
    assert steps.index({"click_text": "Example"}) < steps.index({
        "fill": {"selector": "[data-a2='define'] select[aria-label='Claims to equal']", "value": "mul"}
    }) < steps.index({"click_text": "Run preview"})
    assert steps.index({"click_text": "Run preview"}) < steps.index({
        "wait": {"text": "Ready to store this case-scoped preview result.", "timeout": 15}
    }) < steps.index({"click_text": "Store in session"})


def test_sitecheck_allows_only_the_missing_latest_release_request():
    assert CONFIG["allow"] == [{"kind": "failed_request",
                                "message": "404 https://api.github.com/repos/mkj69/opulse-atoms/releases/latest"}]
