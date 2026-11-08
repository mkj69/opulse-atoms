"""Classify published design text against the current ASCII definition parser."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from opulse.atoms.notation import NotationError, parse_definition

ROOT = Path(__file__).resolve().parents[1]
WORLD_DIR = Path("docs/assets/data/worlds_v2")
CHALLENGE = Path("docs/assets/data/challenge/v2.json")
DESIGNS = Path("docs/worlds/designs.json")
OUTPUT = Path("docs/assets/data/atoms2/parse_status.json")


PLACEHOLDER_LABEL = "placeholder (core notation cannot encode this body)"
_PLACEHOLDER_BODY = re.compile(r"\bwhere\s+false\b|\bfail\s*\(", re.ASCII)


def placeholder_body(text: str) -> bool:
    return bool(_PLACEHOLDER_BODY.search(text.partition("=")[2]))


def classify(text: str) -> bool | str:
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        parse_definition(text)
    except NotationError:
        return False
    return PLACEHOLDER_LABEL if placeholder_body(text) else True


def parses(text: str) -> bool:
    return classify(text) is True


def generate(root: Path = ROOT) -> dict:
    sources = {}
    entries = {}

    def read(path: Path) -> dict:
        raw = (root / path).read_bytes()
        sources[path.as_posix()] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    for path in sorted((root / WORLD_DIR).glob("*.json")):
        relative = path.relative_to(root)
        world = read(relative)
        if world.get("schema") != "opulse.world_v2_export/1":
            continue
        for row in world.get("story", []):
            entries[world["world"] + "/" + row["name"]] = classify(row.get("ascii", row.get("decl")))
    for world_name, design in read(DESIGNS)["worlds"].items():
        for row in design.get("tower", []):
            entries["design/" + world_name + "/" + row["name"]] = classify(row.get("decl"))
    challenge = read(CHALLENGE)
    for ladder in challenge["ladders"].values():
        for task in ladder:
            if task.get("definition") is not None:
                entries[task["id"]] = classify(task["definition"])
    for route in challenge["paths"].values():
        for task in route["steps"]:
            if task.get("definition") is not None:
                entries[task["id"]] = classify(task["definition"])

    index = read(WORLD_DIR / "index.json")
    bridge_file = index.get("bridges")
    if isinstance(bridge_file, dict):
        bridge_file = bridge_file.get("file")
    if bridge_file:
        for bridge in read(WORLD_DIR / bridge_file).get("story", []):
            if bridge.get("decl") is not None:
                entries["bridge/" + bridge["name"]] = classify(bridge["decl"])

    return {"schema": "opulse.atoms2_parse_status/1", "sources": sources,
            "entries": dict(sorted(entries.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed status is stale")
    args = parser.parse_args()
    destination = ROOT / OUTPUT
    content = json.dumps(generate(), indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
            parser.exit(1, f"stale generated data: {destination}\n")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
