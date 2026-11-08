"""Public depth-world export entrypoint."""

import json

from opulse.worlds_v2.export_util import finalize_export

from .deep_export import OUTPUT, build_export

_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8")
