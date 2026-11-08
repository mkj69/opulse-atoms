"""Every committed gen_v2 export decodes with the published-value decoder, and every
four_kinds_path is a dependency chain (integration round 5)."""

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opulse.gen_v2.export import _decode_example

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "docs/assets/data/gen_v2"
DATA = ROOT / "dataset-exports/gen_v2"
INDEX = json.loads((SITE / "index.json").read_text()) if (SITE / "index.json").exists() else {"worlds": {}}
PUBLISHED = sorted(slug for slug, row in INDEX["worlds"].items() if row.get("published"))


def _state(slug):
    return SimpleNamespace(world=SimpleNamespace(
        dialect="legacy-v1" if slug.startswith("classic-") else "atoms-v2"))


def _examples(rows):
    for row in rows:
        yield from row.get("examples", [])


def test_published_index_is_not_empty():
    assert PUBLISHED


@pytest.mark.parametrize("slug", PUBLISHED)
def test_published_examples_decode(slug):
    state = _state(slug)
    compact = json.loads((SITE / f"{slug}.json").read_text())
    with gzip.open(DATA / f"{slug}.jsonl.gz", "rt") as dataset:
        rows = [json.loads(line) for line in dataset]
    for example in _examples(compact.get("entries", []) + compact.get("story", []) + rows):
        for value in example["inputs"]:
            _decode_example(value, state)
        if "ok" in example["outcome"]:
            _decode_example(example["outcome"]["ok"], state)


@pytest.mark.parametrize("slug", PUBLISHED)
def test_four_kinds_path_is_a_dependency_chain(slug):
    path = json.loads((SITE / f"{slug}.json").read_text()).get("four_kinds_path")
    if path is None:
        return
    steps = {row["name"]: row for row in path["steps"]}
    with gzip.open(DATA / f"{slug}.jsonl.gz", "rt") as dataset:
        depends = {row["name"]: row["depends_on"] for row in map(json.loads, dataset)}

    def closure(name, seen):
        for dependency in depends.get(name, ()):
            for item in (dependency, dependency.split(".")[0]):
                if item not in seen:
                    seen.add(item)
                    closure(item, seen)
        return seen

    names = list(steps)
    assert names[0] in closure(names[1], set()), names
    assert names[2] in closure(names[3], set()), names
