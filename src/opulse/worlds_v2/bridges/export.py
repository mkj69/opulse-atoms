"""Build the public, replayable bridge catalogue."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json
from opulse.worlds_v2.integer import hosts as integers
from opulse.worlds_v2.rhythm import hosts as rhythm

from .world import build_library

EXPORT_PATH = Path(__file__).resolve().parents[4] / "docs/assets/data/worlds_v2/bridges/bridges.json"


def _example(library, name, value, text):
    run = library.run(name, (value,), trace=True)
    return {"text": text, "outcome": encode_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace)}


def build_export():
    beats, fractions = build_library()
    rows = []
    for library, name, title, definition, title_zh, definition_zh, source, target, examples in (
        (beats, "beat_row", "Beat row",
         ("Map each 0 to an unlit '.', and each light (1) or heavy (2) beat to a lit '#'. "
          "The resulting grid has one row. Rotation left by k shifts its columns left by k modulo width."),
         "节拍行", "将零拍变成未点亮的点，将轻拍与重拍变成点亮的井号；左旋对应列的循环左移。",
         "rhythm@1", "pixels@1", (
             (rhythm.make_rhythm((2, 0, 1, 0, 2)), "~beat_row(Rhythm<2, 0, 1, 0, 2>)"),
             (rhythm.make_rhythm((0, 0, 0, 0)), "~beat_row(Rhythm<0, 0, 0, 0>)"),
             (rhythm.make_rhythm((0,) * 9), "~beat_row(Rhythm<0, 0, 0, 0, 0, 0, 0, 0, 0>)"),
         )),
        (fractions, "to_frac", "Canonical fraction",
         ("Translate a pair (integer numerator, positive denominator) to a reduced integer-world fraction. "
          "Pair and fraction addition cross-multiply numerators and canonicalize the result."),
         "最简分数", "将整数分子与正整数分母的数对化为最简分数；两侧加法交叉相乘并约分。",
         "integer@2", "integer@2", (
             (integers.pair(-3, 2), "~to_frac(Pair<-3, 2>)"),
             (integers.pair(4, 3), "~to_frac(Pair<4, 3>)"),
             (integers.pair(3, 0), "~to_frac(Pair<3, 0>)"),
         )),
    ):
        card = library.get(name)
        written = replace(card, status="written", evidence=None, contract=None, id=None, cost=Cost())
        digest = export_util.body_sha256(card.body)
        try:
            declaration = notation.print_definition(written)
        except (TypeError, ValueError, notation.NotationError):
            declaration = None
        if declaration is not None and not export_util.source_matches(declaration, digest):
            declaration = None
        rows.append({"kind": "bridge", "name": name, "symbol": f"~{name}",
                     "body_sha256": digest, "design_decl": definition,
                     **({"decl": declaration} if declaration is not None else {}),
                     "title": title, "definition": definition, "title_zh": title_zh,
                     "definition_zh": definition_zh, "source_world": source, "target_world": target,
                     "evidence": card.evidence.to_dict(), "status": card.status,
                     "examples": [_example(library, name, value, text) for value, text in examples]})
    return finalize_export({"story": rows})


def main():
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    from opulse.notation3.export import add_notation3

    EXPORT_PATH.write_text(json.dumps(add_notation3(build_export(), 'worlds_v2'), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
