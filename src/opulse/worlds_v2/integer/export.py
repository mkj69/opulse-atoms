"""Generate exact, replayable arithmetic tower examples from the kernel."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, notation
from opulse.atoms import nodes as n
from opulse.atoms.spec import Cost
from opulse.atoms.values import Card, Ok, encode, encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json
from opulse.worlds_v2.integer.extensions import LAW_DESCRIPTIONS, extend_library
from opulse.worlds_v2.integer.story import build_library, frac
from opulse.worlds_v2.integer.world import DECL_PATH

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/integer.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/integer.json"
TOWER_NAMES = ("nat", "repeat", "mul", "frac", "whole", "qadd", "qmul", "fold_frac",
               "cf_divmod", "cf", "convergents", "bounded_convergent")
FRESH_EXAMPLES = {
    "qadd": "qadd(Frac<mul(2, 3), 7>, Frac<1, 2>)",
    "qmul": "qmul(qadd(Frac<1, 2>, Frac<1, 3>), Frac<3, 5>)",
    "fold_frac": "@fold_frac[qadd](List<qmul(Frac<1, 2>,Frac<2, 3>),Frac<1, 6>>,Frac<0, 1>)",
    "cf_divmod": "cf_divmod(mul(-7, 5), 3)",
    "cf": "CF<qadd(Frac<1, 2>, Frac<5, 3>)>",
    "convergents": "@convergents[cf_step](CF<qmul(Frac<87, 23>, Frac<2, 3>)>)",
    "bounded_convergent": "?bounded_convergent{Pair<CF<qadd(Frac<3, 5>,Frac<1, 2>)>, Nat<8>>}",
}
LAW_LABELS = {
    "add_comm": ("加法交换律", "交换两个加数，和不变。"),
    "mul_comm": ("乘法交换律", "交换两个因数，积不变。"),
    "mul_distrib": ("乘法分配律", "乘法对右侧的加法分配。"),
    "gcd_comm": ("最大公约数交换律", "交换两个整数，最大公约数不变。"),
    "gcd_mul_lcm": ("最大公约数与最小公倍数", "两者的乘积等于原数乘积的绝对值。"),
}
CARD_ENGLISH = {
    "nat": ("Nonnegative integers", "Refines signed integers to values at least zero, rejecting negatives."),
    "repeat": ("Counted iteration", "Applies a supplied unary step exactly the nonnegative count of times."),
    "mul": ("Signed multiplication", "Builds the magnitude by repeated addition and restores the product sign."),
    "frac": ("Reduced fractions", "Rejects zero denominators and divides both components by their gcd, keeping a positive denominator."),
    "whole": ("Whole-number test", "Observes whether a canonical fraction has denominator one."),
    "qadd": ("Fraction addition", "Cross-multiplies denominators and normalizes the resulting fraction."),
    "qmul": ("Fraction multiplication", "Multiplies numerators and denominators before canonical reduction."),
    "fold_frac": ("Fraction list fold", "Combines a list of fractions from left to right with a supplied binary operation."),
    "cf_divmod": ("Euclidean division", "Returns quotient and nonnegative remainder for a strictly positive divisor."),
    "cf": ("Finite continued fraction", "Expands a rational using Euclidean divisions into its unique finite canonical digit list."),
    "convergents": ("Continued-fraction convergents", "Accumulates the rational approximation at every digit using a supplied state step."),
    "bounded_convergent": ("Denominator-bounded convergent", "Selects the last convergent with denominator at most the given bound, or fails if none qualifies."),
}
LADDER_ENGLISH = {
    1: ("Integers up to 20; eight repeats; denominators up to 9; two addends",
        "Build nonnegative counters and reduce small fractions."),
    2: ("Integers up to 200; 60 repeats; denominators up to 60; three to five addends",
        "Compose rational arithmetic and folds over larger inputs."),
    3: ("Integers up to 2000; four to seven digits; denominator bound 100; search up to 128",
        "Find convergents and invert a bounded expression."),
    4: ("Integers up to 100000; eight to twelve digits; six to twelve addends; declared fuel",
        "Account for deeper Euclidean expansion and longer folds."),
    5: ("Problem-specific finite domains and fuel; 12 to 24 digits; up to 20-digit inputs",
        "Prove exact outcomes on a stated scope rather than extrapolating evidence."),
}
NAME_BY_OBJECT = {"Int": None, "Nat": "nat", "Frac": "frac", "CF": "cf",
                  "Hour": "hour", "QuotFrac": "quot_frac",
                  "List": "list", "Pair": "pair"}
NAME_BY_COMBINATOR = {"repeat": "repeat", "fold_frac": "fold_frac", "convergents": "convergents",
                      "sequence": "sequence"}


class Parser:
    def __init__(self, source):
        self.tokens = re.findall(r"-?\d+|[A-Za-z_][A-Za-z_0-9]*|[@?<>()[\]{},]", source)
        if "".join(self.tokens) != re.sub(r"\s+", "", source):
            raise ValueError("invalid expression: " + source)
        self.position = 0

    def take(self, expected=None):
        if self.position >= len(self.tokens):
            raise ValueError("unexpected end of expression")
        token = self.tokens[self.position]
        self.position += 1
        if expected is not None and token != expected:
            raise ValueError(f"expected {expected}, got {token}")
        return token

    def arguments(self, closing):
        arguments = []
        if self.tokens[self.position] != closing:
            arguments.append(self.expression())
            while self.tokens[self.position] == ",":
                self.take(",")
                arguments.append(self.expression())
        self.take(closing)
        return arguments

    def expression(self):
        token = self.take()
        if token == "@":
            name = self.take()
            self.take("[")
            slots = [self.take()]
            while self.tokens[self.position] == ",":
                self.take(",")
                slots.append(self.take())
            self.take("]")
            self.take("(")
            return n.Call(NAME_BY_COMBINATOR[name], tuple(n.Lit(kernel.FnRef(slot)) for slot in slots)
                          + tuple(self.arguments(")")))
        if token == "?":
            name = self.take()
            self.take("{")
            args = self.arguments("}")
            return n.Call(name, args)
        if re.fullmatch(r"-?\d+", token):
            return n.Lit(int(token))
        if token == "k":
            return n.Var("k")
        bracket = self.take()
        if bracket == "<":
            args = self.arguments(">")
            if token == "Int":
                return args[0]
            if token == "List":
                result = n.Call("list_empty")
                for argument in reversed(args):
                    result = n.Call("cons", (argument, result))
                return result
            if token == "Frac":
                return n.Call("frac.make", (n.Call("pair", args),))
            return n.Call("pair" if token == "Pair" else NAME_BY_OBJECT[token] + ".make", args)
        if bracket == "(":
            return n.Call(token, self.arguments(")"))
        raise ValueError("invalid expression")


def parse(source):
    parser = Parser(source)
    result = parser.expression()
    if parser.position != len(parser.tokens):
        raise ValueError("trailing expression")
    return result


def display(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Card):
        if value.sort == "nat":
            return f"Nat<{value.fields[0]}>"
        if value.sort == "frac":
            if value.tag == "val":
                return display(value.fields[0]).replace("Pair<", "Frac<", 1)
            return f"Frac<{value.fields[0]}, {value.fields[1]}>"
        if value.sort == "cf":
            if value.tag == "val":
                return "CF<" + ", ".join(map(str, value.fields[0].fields)) + ">"
            return "CF<" + ", ".join(map(str, value.fields[0].fields)) + ">"
        if value.sort == "list":
            return "List<" + ", ".join(map(display, value.fields)) + ">"
        if value.sort == "pair":
            return "Pair<" + ", ".join(map(display, value.fields)) + ">"
        if value.sort in ("hour", "quot_frac"):
            return ("Hour" if value.sort == "hour" else "QuotFrac") + "<" + display(value.fields[0]) + ">"
    return str(value)


def run_expression(library, text, *, variables=None, fuel=None, trace=False):
    return kernel.evaluate(parse(text), env=variables or {}, scope=library.scope(),
                           limits=kernel.Limits(fuel=fuel), trace=trace)


def example(library, text):
    expression = parse(text)
    try:
        printed = notation.print_expr(expression, library)
        if notation.parse_expr(printed) == expression:
            text = printed
    except (ValueError, TypeError):
        pass
    run = kernel.evaluate(expression, scope=library.scope(), trace=True)
    inputs = []
    if isinstance(expression, n.Call):
        for argument in expression.args:
            outcome = kernel.evaluate(argument, scope=library.scope()).outcome
            if isinstance(outcome, Ok):
                value = outcome.value
                inputs.append({"t": "fn", "v": value.name} if isinstance(value, kernel.FnRef) else encode(value))
    return {"text": text, "inputs": inputs, "outcome": encode_outcome(run.outcome),
            "steps": run.steps, "trace": trace_json(run.trace)}


def declaration_source(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    if definition.kind == "observation":
        written = replace(written, spec=replace(written.spec, extra={"subject": written.spec.reads[0]}))
    try:
        source = notation.print_definition(written, library)
    except (ValueError, TypeError, notation.NotationError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def build_export(library=None):
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    if library is None:
        library = build_library()
    derivation = extend_library(library)
    story = []
    for card, name in zip(design["tower"], TOWER_NAMES):
        definition = library.get(name)
        sample = example(library, card["example"])
        assert isinstance((actual := run_expression(library, card["example"])).outcome, Ok)
        assert display(actual.outcome.value) == card["value"], (name, display(actual.outcome.value), card["value"])
        story.append({"layer": card["layer"], "def_layer": definition.layer, "kind": card["kind"],
                       "name": name, "decl": declaration_source(definition, library),
                       "body_sha256": export_util.body_sha256(definition.body),
                       "design_decl": card["decl"], "plain_zh": card["plain"],
                      "symbol": (name.title() + "<...>" if card["kind"] == "object" else
                                 "@" + name + "[...]" if card["kind"] == "combinator" else
                                 "?" + name + "{...}" if card["kind"] == "observation" else name + "(...)"),
                      "title": CARD_ENGLISH[name][0], "definition": CARD_ENGLISH[name][1],
                      "title_zh": name, "definition_zh": card["plain"],
                      "depends_on": list(definition.depends_on), "body": n.to_json(definition.body),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [sample]})
        if name in FRESH_EXAMPLES:
            story[-1]["examples"].append(example(library, FRESH_EXAMPLES[name]))
    failure = example(library, "?bounded_convergent{Pair<CF<Frac<1, 2>>, Nat<0>>}")
    assert failure["outcome"] == {"bottom": "no_convergent"}
    story[-1]["examples"].append(failure)
    law_examples = {
        "add_comm": "eq(add(2,-1),add(-1,2))",
        "mul_comm": "eq(mul(2,-1),mul(-1,2))",
        "mul_distrib": "eq(mul(2,add(1,-1)),add(mul(2,1),mul(2,-1)))",
        "gcd_comm": "eq(gcd(2,-1),gcd(-1,2))",
        "gcd_mul_lcm": "eq(mul(gcd(2,-1),lcm(2,-1)),abs_int(mul(2,-1)))",
    }
    for name, description in LAW_DESCRIPTIONS.items():
        definition = library.get(name)
        title_zh, definition_zh = LAW_LABELS[name]
        story.append({"layer": len(story) + 1, "kind": "law", "name": name, "symbol": "#" + name,
                      "decl": declaration_source(definition, library),
                      "body_sha256": export_util.body_sha256(definition.body),
                      "design_decl": description,
                      "title": name.replace("_", " ").title(), "definition": description,
                      "title_zh": title_zh, "definition_zh": definition_zh,
                      "def_layer": definition.layer, "depends_on": list(definition.depends_on),
                      "body": n.to_json(definition.body), "status": definition.status,
                      "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                      "cost": definition.cost.to_dict(), "examples": [example(library, law_examples[name])]})
    template = library.get("Quot")
    story.append({"layer": len(story) + 1, "kind": "template", "name": "Quot", "symbol": "Quot[T, canon]",
                  "decl": declaration_source(template, library),
                  "body_sha256": export_util.body_sha256(template.body),
                  "design_decl": "Quotient object template for a base sort and a canonicalizing operation.",
                  "title": "Quotient object template", "definition": "Builds a refined object from a base sort and a canonicalizing operation; verified for pair reduction and clock hours.",
                  "title_zh": "商对象模板", "definition_zh": "按规范化运算从基础类型构造精化对象。",
                  "def_layer": template.layer, "depends_on": [], "body": n.to_json(template.body),
                  "status": template.status, "evidence": template.evidence.to_dict(),
                  "contract": template.contract.to_dict(), "cost": template.cost.to_dict(),
                  "examples": [example(library, "Hour<13>")]})
    for name, text, description in (
        ("quot_frac", "QuotFrac<Pair<2, 4>>", "Reduces a signed integer pair to its unique rational representative."),
        ("hour", "Hour<13>", "Maps an integer clock reading to its residue from 0 to 11."),
    ):
        definition = library.get(name)
        story.append({"layer": len(story) + 1, "kind": "object", "name": name,
                      "symbol": ("QuotFrac<Pair<Int, Int>>" if name == "quot_frac" else "Hour<Int>"),
                      "decl": declaration_source(definition, library),
                      "body_sha256": export_util.body_sha256(definition.body),
                      "design_decl": description,
                      "title": name.replace("_", " ").title(),
                      "definition": description, "def_layer": definition.layer,
                      "title_zh": ("有理数商对象" if name == "quot_frac" else "十二小时钟"),
                      "definition_zh": ("将整数对约分为唯一的有理数表示。" if name == "quot_frac"
                                        else "将整数钟点归约为零至十一。"),
                      "depends_on": list(definition.depends_on), "body": None,
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [example(library, text)]})
    story[13]["derivation"] = {"by": "#mul_comm", "before": "mul(2,-1)",
                                "after": "mul(-1,2)", "rewrite_steps": len(derivation.steps),
                                "charged_steps": derivation.charged_steps}
    showcase = []
    for task in design["showcase"]:
        item = {("why_hard_zh" if key == "why_hard" else "check_zh" if key == "check" else key): value
                for key, value in task.items()}
        expression = task["prompt"].split("Expression: ", 1)[1].split("\n", 1)[0]
        if task["angle"] == "Invert":
            matches = [candidate for candidate in range(128) if
                       (outcome := run_expression(library, expression, variables={"k": candidate}).outcome) ==
                       Ok(frac(26, 25))]
            checked = matches == [42] and task["answer"] == "Nat<42>"
            item["check_method"] = "kernel exhaustive k in 0..127"
        else:
            outcome = run_expression(library, expression).outcome
            checked = isinstance(outcome, Ok) and display(outcome.value) == task["answer"]
            item["check_method"] = "exact kernel evaluation"
        item["answer_checked"] = checked
        assert checked, task["angle"]
        showcase.append(item)
    objects = [{"name": obj["name"], "form": obj["form"],
                "symbol": obj["name"].capitalize() + "<...>",
                "title": obj["name"].replace("_", " ").title(), "definition": obj["doc"],
                "doc": obj["doc"], "doc_zh": "整数与有限严格数据的通用表示",
                "decl": next((line.split(" — ")[0] for line in design["layer0"]["objects"]
                              if line.startswith("obj " + obj["name"].capitalize())), "obj " + obj["name"] + " given")}
               for obj in declaration["objects"]]
    operations = [{"name": op["name"], "symbol": op["name"] + "(...)" , "rule": op["rule"],
                   "title": op["name"].replace("_", " ").title(), "definition": op["rule"],
                   "rule_zh": "严格调用并计一个原子步", "decl": next((line.split(" — ")[0] for line in design["layer0"]["operations"]
                               if line.startswith("op " + op["name"] + "(")), "op " + op["name"] + " given"),
                   "errors": op["errors"], "cost": op["cost"], "inputs": op["inputs"], "output": op["output"]}
                  for op in declaration["operations"]]
    combinators = {**declaration["combinators"], "library": [
        {**item, "symbol": "@" + item["name"] + "[...]",
         "title": item["name"].replace("_", " ").title(),
         "definition": "Runs the first supplied operation, then passes its result to the second."}
        for item in declaration["combinators"].get("library", [])]}
    observation = {**declaration["observation"], "probes": [
        {**probe, "symbol": "?" + probe["name"] + "{...}",
         "title": probe["name"].replace("_", " ").title(),
         "definition": "Reads the granted integer value without modifying it."}
        for probe in declaration["observation"].get("probes", [])]}
    return {"schema": "opulse.world_v2_export/1", "world": "integer", "version": 2, "wave": 1,
            "title": declaration["title"], "title_zh": design["name"], "pitch_zh": design["pitch"],
            "modality_zh": design["modalities"]["text"], "decl": declaration, "tower_source": "depth",
            "layer0": {"objects": objects, "operations": operations,
                       "combinators": combinators, "observation": observation},
            "story": story, "ladder": [{"level": entry["level"], "knobs_zh": entry["knobs"],
                                         "what_changes_zh": entry["what_changes"],
                                         "knobs": LADDER_ENGLISH[entry["level"]][0],
                                         "what_changes": LADDER_ENGLISH[entry["level"]][1]} for entry in design["ladder"]],
            "showcase": showcase,
            "modalities_zh": {name + "_zh": value for name, value in design["modalities"].items()},
            "toy_risk_zh": design["toy_risk"],
            "emerges_zh": design["pitch"], "checking_zh": "逐项有界验证，展示题由核精确重算。",
            "open_kinds": ["object", "operation", "combinator", "observation", "law"],
            "tags": {"domain": "math", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation", "law"],
                     "star_kind": "operation", "reasoning": ["compute", "counting", "equivalence", "search"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full", "agents": 1,
                     "scale": "20-digit inputs, 12 invented definitions", "difficulty": "5 levels from signed arithmetic to exact bounded inversion",
                     "uses": ["rl-training", "evaluation", "interpretability", "teaching"]}}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    data = _build_export_raw(*args, **kwargs)
    for row in data["story"]:
        if row.get("decl") is None:
            row.pop("decl", None)
    return finalize_export(data)


if __name__ == "__main__":
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
