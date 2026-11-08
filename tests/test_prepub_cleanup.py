"""Keep English documentation sources separate from Chinese prose snippets."""

from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import requires_zh_site

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]")
CJK_RUN = re.compile(CJK.pattern + "+")
SHARED_BILINGUAL_JS = frozenset({
    "atoms-legend.js", "challenge.js", "challenge-answer.js", "challenge-modes.js", "home-scales.js",
    "kinds-legend.js", "learn.js", "playground.js", "scales-core.js", "scales-growth.js", "scales-solve.js",
    "scales-tour.js", "stepview.js",
})


def _assert_scale_data_translation_fields(value: object, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            assert not CJK.search(child_key)
            _assert_scale_data_translation_fields(child, child_key)
    elif isinstance(value, list):
        for child in value:
            _assert_scale_data_translation_fields(child, key)
    elif isinstance(value, str) and CJK.search(value):
        assert key.endswith("_zh"), key


def _code_without_chinese(path: Path) -> str:
    text = CJK_RUN.sub(" ", path.read_text(encoding="utf-8"))
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _assert_challenge_chinese_only_in_zh_fields(value, path, key="") -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            _assert_challenge_chinese_only_in_zh_fields(item, path, name)
    elif isinstance(value, list):
        for item in value:
            _assert_challenge_chinese_only_in_zh_fields(item, path, key)
    elif isinstance(value, str) and CJK.search(value):
        assert key.endswith("_zh"), (path, key, value)


def test_english_docs_have_only_the_prompt_format_example() -> None:
    for path in (ROOT / "docs").rglob("*"):
        if path.suffix not in {".md", ".json", ".js", ".css"}:
            continue
        # The Worlds viewer and its generated records are shared by both site
        # builds; their Chinese fields are selected only on the Chinese page.
        if (path.is_relative_to(ROOT / "docs/assets/js/worlds") or
                path.is_relative_to(ROOT / "docs/assets/data/worlds") or
                path.is_relative_to(ROOT / "docs/assets/data/worlds_v2")):
            continue
        if path.parent == ROOT / "docs/assets/js" and path.name in SHARED_BILINGUAL_JS:
            continue
        if ((path.is_relative_to(ROOT / "docs/assets/data/challenge") or
             (path.is_relative_to(ROOT / "docs/assets/data/worlds_v2") and path.name != "computer.json") or
             path.is_relative_to(ROOT / "docs/research/bundles") or
             path == ROOT / "docs/assets/data/induce_tour.json") and path.suffix == ".json"):
            # Shared challenge and worlds_v2 records (and research bundle copies of them) carry
            # translations only in explicit _zh fields (computer.json is the tasks lead's export
            # and keeps the line-based check below).
            _assert_challenge_chinese_only_in_zh_fields(json.loads(path.read_text(encoding="utf-8")), path)
            continue
        if (path.is_relative_to(ROOT / "docs/assets/data/scales") or
                path.is_relative_to(ROOT / "docs/assets/data/atoms")) and path.suffix == ".json":
            _assert_scale_data_translation_fields(json.loads(path.read_text(encoding="utf-8")))
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        chinese = [line for line in lines if CJK.search(line)]
        expected = ["答案：<整数或 NaN>"] if path == ROOT / "docs/guide/benchmark.md" else []
        assert chinese == expected, path
        if expected:
            position = lines.index(expected[0])
            assert lines[position - 1] == "```text"
            assert lines[position + 1] == "```"


@requires_zh_site
def test_legacy_runner_mirror_keeps_published_code() -> None:
    localized = ROOT / "docs_zh/snippets/localized_assets"
    runner = localized / "js/playground.js"
    assert _code_without_chinese(runner) == _code_without_chinese(ROOT / "docs/assets/js/playground.js")
    assert 'src="../../assets/js/playground.js"' in (ROOT / "docs/play/legacy.md").read_text()


@requires_zh_site
def test_peek_languages_keep_the_same_checked_records() -> None:
    english = ROOT / "docs/snippets/peeks"
    chinese = ROOT / "docs_zh/snippets/peeks"
    assert {p.name for p in english.glob("*.json")} == {p.name for p in chinese.glob("*.json")}
    for path in english.glob("*.json"):
        en = json.loads(path.read_text(encoding="utf-8"))
        zh = json.loads((chinese / path.name).read_text(encoding="utf-8"))
        assert not CJK.search(path.read_text(encoding="utf-8")), path
        assert {key: value for key, value in zh.items() if not key.endswith("_zh") and key != "records"} == {
            key: value for key, value in en.items() if key != "records"}
        assert [{key: value for key, value in record.items() if not key.endswith("_zh")}
                for record in zh["records"]] == en["records"]
