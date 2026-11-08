"""Kernel-generated, source-checked calendar tower and showcase."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, notation, values
from opulse.atoms import nodes as n
from opulse.atoms.spec import Cost
from opulse.atoms.values import Bottom, Card, Ok
from opulse.worlds_v2.export_util import (
    body_sha256,
    finalize_export,
    source_matches,
    trace_json,
)

from . import hosts
from .deep import build_library, c, lit
from .world import decl

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / "docs/assets/data/worlds_v2/calendar.json"
DESIGN = ROOT / "worlds/catalogue/depth/calendar.json"

TOWER_NAMES = ("LeapDay", "week_later", "workday", "seek", "MonthSpan", "month_end",
               "month_fold", "weekday_count", "nth_weekday", "Holiday", "open_day", "settle")
TITLES = ("Leap day", "One week later", "Business weekday", "Bounded search",
          "Checked month", "Inclusive month end", "Inclusive month fold", "Weekday count",
          "Nth weekday", "Observed holiday", "Open business day", "Monthly settlement")

def ascii_declaration(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (ValueError, TypeError):
        return None
    return source if source_matches(source, body_sha256(definition.body)) else None


def example_text(expression, library):
    try:
        return notation.print_expr(expression, library)
    except (ValueError, TypeError):
        if expression.fn in ("LeapDay.make", "Holiday.make"):
            return expression.fn + "(" + ", ".join(notation.print_value(arg.value)
                                                    for arg in expression.args) + ")"
        if expression.fn == "seek":
            return ("@seek[" + ", ".join(arg.value.name for arg in expression.args[:2]) + "](" +
                    ", ".join(notation.print_value(arg.value) for arg in expression.args[2:]) + ")")
        raise


def display(value):
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, Card):
        if value.sort == "date":
            return f"Date<{value.fields[0]:04d}-{value.fields[1]:02d}-{value.fields[2]:02d}>"
        if value.sort in ("LeapDay", "Holiday"):
            return f"{value.sort}<{display(value.fields[0])[5:-1]}>"
        if value.sort == "MonthSpan":
            start = value.fields[0].fields[0]
            return f"MonthSpan<{start.fields[0]:04d}-{start.fields[1]:02d}>"
        if value.sort == "bool":
            return value.tag
    if isinstance(value, tuple):
        return "List<" + ", ".join(map(display, value)) + ">"
    return str(value)


def checked_inputs(expression):
    inputs = []
    for arg in expression.args:
        if not isinstance(arg, n.Lit):
            raise TypeError("example arguments must be evaluated before running a card")
        inputs.append(values.encode(arg.value))
    return inputs


def examples(library):
    leap = hosts.to_card(2000, 2, 29)
    march = hosts.to_card(2000, 3, 7)
    span = library.run("month_span", (2032, 2)).outcome
    if not isinstance(span, Ok):
        raise TypeError(span)
    leap_make = c("LeapDay.make", lit(leap))
    week = c("week_later", lit(leap))
    return (
        ("LeapDay.make(Date<2000-02-29>)", leap_make),
        ("week_later(Date<2000-02-29>)", week),
        ("?workday{Date<2000-03-07>}", c("workday", lit(march))),
        ("@seek[next_date, workday](Date<2000-03-07>, 3)", c("seek", lit(kernel.FnRef("next_date")),
                                                          lit(kernel.FnRef("workday")), lit(march), lit(3))),
        ("month_span(2000, 2)", c("month_span", lit(2000), lit(2))),
        ("month_end(2032, 2)", c("month_end", lit(2032), lit(2))),
        ("@month_fold[next_date, count_workday](MonthSpan<2032-02>, 0)",
         c("month_fold", lit(kernel.FnRef("next_date")), lit(kernel.FnRef("count_workday")),
           lit(span.value), lit(0))),
        ("weekday_count(2032, 2)", c("weekday_count", lit(2032), lit(2))),
        ("nth_weekday(2032, 11, 4, 3)", c("nth_weekday", lit(2032), lit(11), lit(4), lit(3))),
        ("Holiday.make(Date<2032-11-25>)", c("Holiday.make", lit(hosts.to_card(2032, 11, 25)))),
        ("?open_day{Date<2032-11-25>}", c("open_day", lit(hosts.to_card(2032, 11, 25)))),
        ("settle(2032, 12)", c("settle", lit(2032), lit(12))),
    )


def run_example(library, expression):
    if not isinstance(expression, n.Call) or any(not isinstance(arg, n.Lit) for arg in expression.args):
        raise TypeError("example must call a card with evaluated arguments")
    return library.run(expression.fn, tuple(arg.value for arg in expression.args), trace=True)


def _showcase(source, library):
    compute = []
    for year, month in ((2031, 11), (2031, 12), *((2032, month) for month in range(1, 13)),
                        (2033, 1), (2033, 2)):
        run = library.run("settle", (year, month))
        if not isinstance(run.outcome, Ok):
            raise TypeError((year, month, run.outcome))
        compute.append(run.outcome.value)
    invert = []
    for year in range(2000, 2100):
        run = library.run("nth_weekday", (year, 2, 5, 3))
        if isinstance(run.outcome, Bottom):
            continue
        if not isinstance(run.outcome, Ok):
            raise TypeError(run.outcome)
        fifth = run.outcome.value
        if fifth.fields[2] == 29 and library.run("settle", (year, 2)).outcome == Ok(fifth):
            invert.append(year)
    decision = [True]
    for year in range(2000, 2100):
        count = library.run("weekday_count", (year, 12)).outcome
        if not isinstance(count, Ok):
            raise TypeError(count)
        if count.value != 23:
            continue
        end = library.run("month_end", (year, 12)).outcome
        settled = library.run("settle", (year, 12)).outcome
        if not isinstance(end, Ok) or not isinstance(settled, Ok):
            raise TypeError((end, settled))
        if end.value != settled.value:
            decision = [False, year, count.value, end.value, settled.value]
            break
    computed = (compute, invert, decision)
    tasks = []
    for task, result in zip(source["showcase"], computed):
        actual = display(tuple(result))
        if actual != task["answer"]:
            raise ValueError(f"showcase {task['angle']}: {actual} != {task['answer']}")
        tasks.append({**{name if name not in ("check", "why_hard") else name + "_zh": value
                         for name, value in task.items()}, "answer_checked": True,
                      "check_method": "kernel calls for the complete stated year/month domain"})
    return tasks


def build_export(library=None) -> dict:
    source = json.loads(DESIGN.read_text(encoding="utf-8"))
    declaration = json.loads((ROOT / "worlds/decl/v2/calendar@1.json").read_text(encoding="utf-8"))
    if library is None:
        library = build_library()
    story = []
    for source_entry, name, title, (_, expression) in zip(source["tower"], TOWER_NAMES,
                                                             TITLES, examples(library)):
        definition = library.get(name)
        run = run_example(library, expression)
        if not isinstance(run.outcome, Ok) or display(run.outcome.value) != source_entry["value"]:
            raise ValueError(f"tower {name}: {run.outcome} != {source_entry['value']}")
        body = n.to_json(definition.body) if isinstance(definition.body, n.NODE_TYPES) else None
        symbol = (f"@{name}[step, {'accept' if name == 'seek' else 'accumulate'}]"
                  if definition.kind == "combinator" else
                  f"?{name}{{s}}" if definition.kind == "observation" else
                  f"{name}<...>" if definition.kind == "object" else f"{name}(...)")
        story.append({"layer": definition.layer, "tower_position": source_entry["layer"],
                      "def_layer": definition.layer,
                      "kind": definition.kind, "name": name, "symbol": symbol,
                      "title": title, "definition": title + ": " + definition.contract.guarantees,
                      "body_sha256": body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := ascii_declaration(definition, library)) else {}),
                      "design_decl": source_entry["decl"], "plain_zh": source_entry["plain"],
                      "title_zh": source_entry["plain"].split("，")[0],
                      "definition_zh": source_entry["plain"], "depends_on": list(definition.depends_on),
                      "body": body, "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [{"text": example_text(expression, library), "inputs": checked_inputs(expression),
                                    "outcome": values.encode_outcome(run.outcome),
                                    "steps": run.steps, "trace": trace_json(run.trace)}]})
    failed = library.run("week_later", (hosts.to_card(2099, 12, 27),), trace=True)
    story[1]["examples"].append({"text": example_text(c("week_later", lit(hosts.to_card(2099, 12, 27))), library),
                                 "inputs": [values.encode(hosts.to_card(2099, 12, 27))],
                                 "outcome": values.encode_outcome(failed.outcome),
                                 "steps": failed.steps, "trace": trace_json(failed.trace)})
    fresh = {
        "week_later": ("week_later(Date<2004-02-29>)",
                       c("week_later", lit(hosts.to_card(2004, 2, 29)))),
        "workday": ("?workday{Date<2004-03-01>}", c("workday", lit(hosts.to_card(2004, 3, 1)))),
        "seek": ("@seek[next_date, workday](Date<2000-03-06>, 3)",
                 c("seek", lit(kernel.FnRef("next_date")), lit(kernel.FnRef("workday")),
                   lit(hosts.to_card(2000, 3, 6)), lit(3))),
        "weekday_count": ("weekday_count(2032, 3)",
                          c("weekday_count", lit(2032), lit(3))),
        "Holiday": ("Holiday.make(Date<2032-01-19>)",
                    c("Holiday.make", lit(hosts.to_card(2032, 1, 19)))),
        "open_day": ("?open_day{Date<2004-12-31>}",
                     c("open_day", lit(hosts.to_card(2004, 12, 31)))),
    }
    for name, (_, expression) in fresh.items():
        run = run_example(library, expression)
        if not isinstance(run.outcome, Ok):
            raise TypeError(f"fresh {name}: {run.outcome}")
        example = {"text": example_text(expression, library), "inputs": checked_inputs(expression),
                   "outcome": values.encode_outcome(run.outcome), "steps": run.steps,
                   "trace": trace_json(run.trace)}
        story[TOWER_NAMES.index(name)]["examples"].append(example)
    layer0 = {}
    for group in ("objects", "operations", "combinators", "observations"):
        rows = []
        for original in source["layer0"][group]:
            ascii_decl, doc_zh = original.split(" — ", 1)
            ascii_decl = ascii_decl.encode("ascii", "ignore").decode("ascii")
            rows.append({"decl": ascii_decl, "doc_zh": doc_zh, "title": group[:-1].title(),
                         "definition": "A given calendar " + group[:-1] + "."})
        layer0[group] = rows
    layer0["combinators"] = {**declaration["combinators"], "entries": layer0["combinators"]}
    layer0["observation"] = {**declaration["observation"], "entries": layer0.pop("observations")}
    layer0["objects"] += [{"name": item["name"], "form": item["form"],
                            "decl": f"obj {item['name']} given",
                            "title": item["name"], "definition": item.get("doc", ""),
                            "symbol": item["name"], "doc": item.get("doc", ""), "doc_zh": ""}
                           for item in declaration["objects"]]
    layer0["operations"] += [{"name": item["name"], "symbol": item["name"],
                               "decl": f"op {item['name']} given",
                               "title": item["name"], "definition": item["rule"],
                               "rule": item["rule"], "rule_zh": "", "errors": item["errors"],
                               "cost": item["cost"], "inputs": item["inputs"], "output": item["output"]["sort"]}
                              for item in declaration["operations"]]
    return {"schema": "opulse.world_v2_export/1", "world": "calendar", "version": 1,
            "wave": 3, "title": "Across leap day: century settlements", "title_zh": source["name"],
            "pitch_zh": source["pitch"], "modality_zh": "日历／时间", "decl": declaration,
            "tower_source": "depth", "layer0": layer0, "story": story,
            "ladder": source["ladder"], "showcase": _showcase(source, library),
            "modalities_zh": {f"{name}_zh": text for name, text in source["modalities"].items()},
            "toy_risk_zh": source["toy_risk"],
            "open_kinds": list(decl().open_kinds),
            "tags": {"domain": "time", "modalities": ["text", "image", "audio"],
                     "open_kinds": list(decl().open_kinds), "star_kind": "combinator",
                     "reasoning": ["compute", "search", "counting"], "state": "stateless",
                     "outcomes": "deterministic", "visibility": "full", "agents": 1,
                     "scale": "36525 dates, 1200 months, 12 tower cards",
                     "difficulty": "one week through century-wide inference",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "emerges_zh": source["pitch"], "checking_zh": "逐日按公历检验月末与节日；核对设计参考及完整百年展示答案。"}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8")
