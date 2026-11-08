"""Build the first-screen integer tower from promoted core records and kernel runs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from opulse.atoms import kernel, nodes
from opulse.atoms.kernel import FnRef
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.spec import Contract, Definition, ObservationSpec
from opulse.atoms.values import Ok, encode, encode_outcome
from opulse.worlds_v2.export_util import trace_json
from opulse.worlds_v2.integer.adapter import check_local
from opulse.worlds_v2.integer.story import definitions, frac, pair, scope_for
from opulse.worlds_v2.integer.world import new_library
from tools.atoms2_core_source import printed_declaration, printed_label

OUTPUT = ROOT / "docs/assets/data/atoms2/first_tower.json"
NAMES = ("nat", "repeat", "mul", "frac", "qmul", "seen_value")
DISPLAY_NAMES = {"nat": "Nat", "frac": "Frac"}


def core_declaration(definition):
    printed = printed_declaration(definition)
    if printed["text"] is not None:
        return printed["text"], printed_label(printed)

    label = "Core summary"
    if definition.name == "nat":
        return "Natural numbers keep nonnegative integers.", label
    if definition.name == "frac":
        return "Fractions reject a zero denominator and reduce numerator and denominator with a consistent sign.", label
    if definition.name == "repeat":
        return "Repeat applies a supplied operation to a seed the requested number of times.", label
    if definition.name == "mul":
        bindings = {node.name: node.value for node in nodes.walk(definition.body) if isinstance(node, nodes.Let)}
        counter = bindings["counter"]
        product = bindings["product"]
        if not (isinstance(counter, nodes.Call) and counter.fn == "repeat" and
                isinstance(counter.args[0], nodes.Lit) and isinstance(counter.args[0].value, FnRef) and
                isinstance(product, nodes.Rec)):
            raise ValueError("mul core body changed; revise its summary")
        return "Multiplication counts ticks, adds the left magnitude once per tick, and negates the result when input signs differ.", label
    if definition.name == "qmul":
        return "Fraction multiplication multiplies the numerators and denominators, then constructs a reduced fraction.", label
    raise ValueError(f"no faithful compact summary for {definition.name}")


def fallback_html(artifact):
    lines = []
    for card in artifact["cards"]:
        label = html.escape(card["summary_label"])
        summary = html.escape(card["record_summary"]).replace("[", "&#91;").replace("]", "&#93;")
        dependencies = ", ".join(DISPLAY_NAMES.get(name, "@" + name if name == "repeat" else name) for name in card["invented_dependencies"])
        uses = f" Uses {html.escape(dependencies)}." if dependencies else ""
        evidence = card.get("evidence") or {}
        scope = evidence.get("scope") or {}
        checked = scope.get("checked")
        verified = (isinstance(checked, dict) and isinstance(checked.get("sha256"), str) and
                    re.fullmatch(r"[0-9a-f]{64}", checked["sha256"]) is not None and
                    isinstance(checked.get("size"), int) and checked["size"] > 0 and
                    isinstance(scope.get("size"), int) and scope["size"] > 0 and
                    evidence.get("method") == "bounded")
        badge = (f'Bounded ({scope["size"]} cases)' if verified else 'scope not recorded')
        badge_class = 'first-tower-badge' if verified else 'first-tower-scope'
        source = f'<code>{summary}</code>' if card["summary_label"].startswith("Printed from") else summary
        lines.append(f'<li>L{card["layer"]} {label}: {source}{"" if summary.endswith(".") else "."}{uses} '
                     f'<span class="{badge_class}">{badge}</span></li>')
    failure = artifact.get("failing") or {}
    run_label = ('Executable (core run artifact)' if failure.get('call') and 'outcome' in failure and
                 isinstance(failure.get('steps'), int) else 'scope not recorded')
    run_class = 'first-tower-badge' if run_label.startswith('Executable') else 'first-tower-scope'
    failure_text = ('returns <code>Bottom(invalid)</code> through the core.' if run_class == 'first-tower-badge'
                    else 'has no recorded outcome.')
    lines.append(f'<li><code>Frac&lt;1, 0&gt;</code> <span class="{run_class}">{run_label}</span> '
                 f'{failure_text}</li>')
    return "\n".join(lines)


def build_tower_library():
    library = new_library()
    selected = set(NAMES) - {"seen_value"}
    for definition in definitions():
        if definition.name not in selected:
            continue
        library.write(definition)
        if definition.kind == "object":
            library.check(definition.name)
        else:
            check_local(library, definition.name)
        request = scope_for(definition.name)
        sample = ((kernel.FnRef(request.extra["op_family"][0]), *request.domain[0])
                  if definition.kind == "combinator" else request.domain[0])
        library.make_callable(definition.name, (sample,))
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract(f"{definition.name}: exact over the stated finite scope"))
        selected.remove(definition.name)
    if selected:
        raise ValueError(f"tower definitions missing: {', '.join(sorted(selected))}")
    return library


def add_core_observation(library):
    """Use the granted integer probe; do not bypass the core observation checker."""
    body = nodes.Call("value", (nodes.Var("value"),))
    record = Definition("seen_value", "observation", "invented", 1, ("value",),
                        ObservationSpec("seen_value", ("value",), body, extra={"subject": "value"}), body)
    library.write(record)
    library.check(record.name)
    library.make_callable(record.name, ((13,),))
    domain = tuple((value,) for value in range(-10, 11))
    Library.verify(library, record.name, VerifyRequest("bounded", domain,
                   {"domain": "integer values -10..10", "size": len(domain)}, reference=lambda value: value))
    library.account(record.name)
    library.promote(record.name, Contract("probe-only view on the stated finite scope"))
    return library


def cases(library):
    count_run = library.run("nat.make", (5,)).outcome
    if not isinstance(count_run, Ok):
        raise TypeError("tower inputs must be constructible by the core")
    count = count_run.value
    product = library.run("qmul", (frac(-1, 2), frac(2, 3))).outcome
    if not isinstance(product, Ok):
        raise TypeError("qmul must produce the observed fraction")
    denominator = library.run("denominator", (product.value,)).outcome
    if not isinstance(denominator, Ok):
        raise TypeError("the observed fraction must have a denominator")
    return {
        "nat": ((5,), "Nat<5>"),
        "repeat": ((FnRef("succ"), -2, count), "@repeat[succ](-2, Nat<5>)"),
        "mul": ((-6, 5), "mul(-6, 5)"),
        "frac": ((pair(-3, 4),), "Frac<-3, 4>"),
        "qmul": ((frac(-1, 2), frac(2, 3)), "qmul(Frac<-1, 2>, Frac<2, 3>)"),
        "seen_value": ((denominator.value,), f"?seen_value{{{denominator.value}}}"),
    }


def input_digest():
    digest = hashlib.sha256()
    paths = sorted((ROOT / "src/opulse/atoms").glob("*.py"))
    paths += sorted((ROOT / "src/opulse/worlds_v2/integer").glob("*.py"))
    paths += [ROOT / "src/opulse/worlds_v2/export_util.py",
              ROOT / "worlds/decl/v2/integer@2.json", Path(__file__),
              ROOT / "tools/atoms2_core_source.py", ROOT / "tools/atoms2_parse_status.py"]
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode("ascii") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_case(library, name, args, text):
    target = name + ".make" if library.get(name).kind == "object" else name
    run = library.run(target, args, trace=True)
    checked = (tuple((value,) for value in range(-10, 11)) if name == "seen_value" else
               scope_for(name).domain if name != "denominator" else None)
    domain_args = args[1:] if name == "repeat" else args
    return {"call": text, "target": target, "args": [encode(arg) for arg in args],
            **({"outside_checked_scope": True} if checked is not None and domain_args not in checked else {}),
            "outcome": encode_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace, max_nodes=12)}


def build_export():
    library = add_core_observation(build_tower_library())
    examples = cases(library)
    records = []
    for name in NAMES:
        definition = library.get(name)
        args, text = examples[name]
        evidence = definition.evidence
        dependencies = list(definition.depends_on)
        invented = sorted({dependency.split(".")[0] for dependency in dependencies
                           if library.get(dependency.split(".")[0]).origin == "invented"})
        computed_layer = 1 + max((library.get(dep).layer for dep in invented), default=0)
        if computed_layer != definition.layer:
            raise ValueError(f"{name}: inconsistent layer {definition.layer} != {computed_layer}")
        declaration, summary_label = core_declaration(definition)
        example = run_case(library, name, args, text)
        if name == "seen_value":
            product_args, product_text = examples["qmul"]
            product = library.run("qmul", product_args).outcome
            if not isinstance(product, Ok):
                raise ValueError("qmul must return the observation's source value")
            numerator, denominator = product.value.fields[0].fields
            example["input_from"] = [run_case(library, "qmul", product_args, product_text),
                                     run_case(library, "denominator", (product.value,),
                                              f"denominator(Frac<{numerator}, {denominator}>)")]
        records.append({"name": name, "display_name": DISPLAY_NAMES.get(name, name),
                        "kind": definition.kind, "record_summary": declaration,
                        "summary_label": summary_label,
                        "dependencies": dependencies, "invented_dependencies": invented,
                        "layer": computed_layer, "status": definition.status,
                        "evidence": {"method": evidence.method, "scope": evidence.scope,
                                     "checks": list(evidence.checks), "content_hash": evidence.content_hash},
                        "example": example})
    failing = run_case(library, "frac", (pair(1, 0),), "Frac<1, 0>")
    if "bottom" not in failing["outcome"]:
        raise ValueError("the invalid denominator must fail in the core")
    return {"schema": "opulse.first_tower/1", "inputs_sha256": input_digest(),
            "world": "integer", "cards": records, "failing": failing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed tower or fallback is stale")
    args = parser.parse_args()
    try:
        artifact = build_export()
    except Exception as error:
        raise RuntimeError("integer world code failed while building the tower (not stale UI data)") from error
    from opulse.notation3.export import add_notation3

    output = json.dumps(add_notation3(artifact, 'atoms2', source='atoms2/first_tower.json'),
                        indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != output:
            parser.exit(1, f"stale generated data: {OUTPUT}\n")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(output, encoding="utf-8")
    for page in (ROOT / "docs/index.md", ROOT / "docs/learn/index.md"):
        content = page.read_text()
        revised, count = re.subn(r'(?<=<ol class="first-tower-fallback" data-first-tower-fallback aria-label="Integer tower summary without JavaScript">\n).*?(?=\n</ol>)',
                                 fallback_html(artifact), content, flags=re.DOTALL)
        if count != 1:
            raise ValueError(f"first tower fallback missing from {page}")
        if args.check:
            if revised != content:
                parser.exit(1, f"stale generated fallback: {page}\n")
        else:
            page.write_text(revised)


if __name__ == "__main__":
    main()
