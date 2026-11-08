"""Site handoff index for installed meta worlds (atoms-meta 8)."""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXPORTS = Path("docs/assets/data/meta")
DECLARATIONS = Path("worlds/decl/meta")
WORLDS = ("code", "vonneumann", "compiler", "builder")


def present_worlds(root=ROOT):
    """Find complete world layouts without requiring all four worlds to be installed."""
    root = Path(root)
    return tuple(name for name in WORLDS
                 if (root / DECLARATIONS / f"{name}@1.json").is_file()
                 and (root / EXPORTS / f"{name}.json").is_file()
                 and all((root / "src/opulse/meta/worlds" / name / f"{part}.py").is_file()
                         for part in ("world", "story", "showcase", "export")))


def build_index(root=ROOT):
    """Summarize the published exports; do not rerun their costly stories."""
    root = Path(root)
    spec = (root / "docs/spec/atoms-meta.md").read_text(encoding="utf-8")
    match = re.search(r"^Spec version:\s*`([^`]+)`", spec, re.MULTILINE)
    if match is None:
        raise ValueError("docs/spec/atoms-meta.md: missing Spec version line")
    worlds = []
    for name in present_worlds(root):
        exported = json.loads((root / EXPORTS / f"{name}.json").read_text(encoding="utf-8"))
        story = exported["story"]
        counts = Counter(item["kind"] for item in story)
        callable_only = []
        for item in story:
            if item["status"] in ("callable", "verified"):
                evidence = item.get("evidence") or {}
                reason = (item.get("reason") or item.get("callable_reason")
                          or ("sampled evidence is not promotable" if evidence.get("method") == "sampled"
                              else "not promoted"))
                callable_only.append({"name": item["name"], "kind": item["kind"], "reason": reason})
        worlds.append({"file": f"{name}.json", "world": exported["world"],
                       "version": exported["version"], "title": exported["title"],
                       "pitch": exported["pitch"], "tags": exported["tags"],
                       "story": [{key: item[key] for key in
                                  ("layer", "kind", "name", "symbol", "status")}
                                 | {"method": (item.get("evidence") or {}).get("method")}
                                 | {key: item[key] for key in ("interface", "produces", "family_scope")
                                    if key in item}
                                 for item in story],
                       "counts": {"by_kind": dict(sorted(counts.items())),
                                  "promoted": sum(item["status"] == "promoted" for item in story),
                                  "callable_only": callable_only},
                       "showcase_angles": [item.get("angle") for item in exported["showcase"]]})
    return {"schema": "opulse.meta_index/1", "spec_version": match.group(1), "worlds": worlds}


def main():
    path = ROOT / EXPORTS / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_index(), sort_keys=True, indent=1, ensure_ascii=True) + "\n",
                    encoding="utf-8")


if __name__ == "__main__":
    main()
