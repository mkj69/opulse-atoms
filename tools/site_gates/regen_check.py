"""Block publication when committed UI exports differ from their generators."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORTERS = (
    "notation3_export.py",
    "atoms2_ui_export.py",
    "atoms2_walk_export.py",
    "atoms2_tower_export.py",
    "atoms2_roads_export.py",
    "atoms2_grammar_export.py",
    "atoms2_parse_status.py",
    "research_bundle.py",
)


def main() -> int:
    for exporter in EXPORTERS:
        command = [sys.executable, str(ROOT / "tools" / exporter), "--check"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            print(f"Regeneration gate failed: {exporter}\n{detail}", file=sys.stderr)
            return 1
    print("Regeneration gate passed: all UI exports match their generators.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
