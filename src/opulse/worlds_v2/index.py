"""Index of the generated world exports (docs/assets/data/worlds_v2/index.json).

Run `python -m opulse.worlds_v2.index` after regenerating any world export.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "docs" / "assets" / "data" / "worlds_v2"
DECLS = ROOT / "worlds" / "decl" / "v2"
SCHEMA = "opulse.world_v2_index/1"


OTHER_OWNERS = frozenset({"computer"})  # exports in this folder written by the tasks lead


def exports() -> dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(DATA.glob("*.json"))
            if path.name != "index.json" and path.stem not in OTHER_OWNERS}


def build_index() -> dict:
    worlds = []
    for name, data in exports().items():
        worlds.append({
            "world": name, "version": data["version"], "wave": data["wave"],
            "title": data["title"], "title_zh": data["title_zh"], "pitch_zh": data["pitch_zh"],
            "modality_zh": data["modality_zh"], "file": f"{name}.json",
            "world_hash": data.get("world_hash", data["decl"]["lock"]["world_hash"]),
            "story": [{"layer": item.get("layer"), "kind": item["kind"], "name": item["name"],
                       "symbol": item["symbol"], "title": item.get("title"), "title_zh": item.get("title_zh"),
                       "status": item["status"],
                       "method": (item.get("evidence") or {}).get("method")}
                      for item in data["story"]],
        })
    worlds.sort(key=lambda item: (item["wave"], item["world"]))
    from opulse.notation3.export import add_notation3

    return add_notation3({"schema": SCHEMA, "worlds": worlds}, "worlds_v2")


def main() -> None:
    text = json.dumps(build_index(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    (DATA / "index.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
