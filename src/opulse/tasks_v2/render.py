"""Surface rendering for finite tasks (docs/spec/atoms-v2.md, sections 2 and 12)."""

from __future__ import annotations

import itertools
import json
import re
from xml.etree import ElementTree

from opulse.tasks_v2.render_image import render_robot, render_value


def render(task, modality: str) -> dict[str, str]:
    """Return the learner's prompt or its SVG view without changing task truth."""
    selected = task.get("modality", "text") if isinstance(task, dict) else task.modality
    if modality != selected:
        raise ValueError("requested modality differs from task modality; legacy operation tasks support text modality only")
    if isinstance(task, dict):
        if task.get("world") != "computer@1":
            raise ValueError("unsupported task world")
        if modality == "image":
            return render_machine(task)
        from opulse.tasks_v2.angles.computer import observed_input

        visible = observed_input(task) if "input" in task else {}
        return {"text": task.get("prompt", {}).get("en") or
                f"Computer {task['angle']} task. Visible input: " +
                json.dumps(visible, sort_keys=True, separators=(",", ":"))}
    if modality == "text":
        return {"text": task.prompt["en"]}
    if modality != "image":
        raise ValueError("unsupported task modality")
    if task.world == "action@1" and task.kind == "observation":
        from opulse.tasks_v2.kernel_engine import unwire

        question = task.question
        states = (question.get("states") if task.angle in ("compute", "decide")
                  and "states" in question else [question["state"]])
        hidden = task.observation["show"]["input"] == "hidden"
        probes = (("front_wall",) if question["observation"] == "front_wall_only" else
                  ("front_water",) if question["observation"] == "front_water_only" else
                  ("front_wall", "front_water")) if hidden else ()
        svg = _robot_images([unwire(state) for state in states], hidden, probes)
    else:
        svg = render_value(task.family)
    return _image_payload(svg)


def _image_payload(svg: str) -> dict[str, str]:
    root = ElementTree.fromstring(svg)
    return {"image_svg": svg, "fidelity": root.attrib["data-fidelity"],
            "shows": root.attrib["data-shows"]}


def _robot_images(states, hidden: bool, probes) -> str:
    if len(states) == 1:
        return render_robot(states[0], learner_view=hidden, probes=probes)
    images = [ElementTree.fromstring(render_robot(state, learner_view=hidden, probes=probes))
              for state in states]
    namespace = "http://www.w3.org/2000/svg"
    root = ElementTree.Element(f"{{{namespace}}}svg", {
        "viewBox": f"0 0 {max(int(image.attrib['width']) for image in images)} "
                   f"{sum(int(image.attrib['height']) for image in images)}",
        "data-fidelity": "lossy", "data-shows": "ordered robot states; " +
        images[0].attrib["data-shows"],
    })
    offset = 0
    for image in images:
        image.attrib["y"] = str(offset)
        offset += int(image.attrib["height"])
        root.append(image)
    result = ElementTree.tostring(root, encoding="unicode")
    if len(result.encode("utf-8")) >= 20_000:
        raise ValueError("SVG exceeds 20 KB")
    return result


def render_machine(task: dict) -> dict[str, str]:
    """Draw only the computer registers granted by the learner observation."""
    from opulse.tasks_v2.angles.computer import observed_input

    if "input" in task:
        visible = observed_input(task)
        notation = "Machine<" + ", ".join(f"{name}={value}" for name, value in visible.items()) + ">"
        return _image_payload(render_value(notation))
    if "examples" in task:
        example = task["examples"][0]
        return render_machine({**task, "input": example["input"]})
    return _image_payload(render_value(f"Program<{task['angle']}>"))


def show_value(value_json: dict, world: str) -> str:
    """Render an encoded value or outcome without exposing its wire representation."""
    if "ok" in value_json:
        return show_value(value_json["ok"], world)
    if "bottom" in value_json or value_json.get("t") == "nan":
        return "NaN" if world.split("@")[0] in ("integer", "clock", "lists", "strings") else "Bottom"
    if "unknown" in value_json:
        return f"Unknown({value_json['unknown']})"
    sort = value_json["t"]
    if sort == "int":
        return str(value_json["v"])
    if sort == "str":
        return json.dumps(value_json["v"], ensure_ascii=False)
    if sort == "bool":
        return "true" if value_json.get("tag", value_json.get("v")) in ("true", True) else "false"
    if sort in ("list", "list[int]"):
        items = value_json.get("f", value_json.get("v", ()))
        return "List<" + ", ".join(show_value(item, world) if isinstance(item, dict) else str(item)
                                      for item in items) + ">"
    if "tag" in value_json:
        fields = ", ".join(show_value(item, world) for item in value_json.get("f", ()))
        return f"{value_json['tag']}({fields})" if fields else value_json["tag"]
    return json.dumps(value_json["v"], ensure_ascii=False)


def _sequence_domain(domain: list[dict], sort: str) -> str | None:
    if sort not in ("str", "list[int]") or not domain:
        return None
    if sort == "str":
        strings = [item["v"] for item in domain if item.get("t") == "str"]
        if len(strings) != len(domain):
            return None
        sequences = [tuple(item) for item in strings]
    else:
        try:
            sequences = [tuple(item["v"] if isinstance(item, dict) else item
                               for item in value.get("f", value.get("v", ())))
                         for value in domain]
        except (KeyError, TypeError):
            return None
        if any(type(item) is not int for seq in sequences for item in seq):
            return None
    if () not in sequences:
        return None
    alphabet = sorted({item for seq in sequences for item in seq}, key=lambda item: str(item))
    max_length = max(map(len, sequences))
    expected = {tuple(seq) for length in range(max_length + 1)
                for seq in itertools.product(alphabet, repeat=length)}
    if set(sequences) != expected or len(sequences) != len(expected):
        return None
    letters = (json.dumps(item, ensure_ascii=False) for item in alphabet) if sort == "str" else (
        str(item) for item in alphabet)
    kind = "strings" if sort == "str" else "lists"
    return f"all {kind} of length ≤ {max_length} over {{{', '.join(letters)}}}"


def _domain(domain: list[dict], param: dict, world: str) -> str:
    sequence = _sequence_domain(domain, param.get("type", ""))
    if sequence is not None:
        return sequence
    if domain and all(value.get("t") == "int" for value in domain):
        ints = [value["v"] for value in domain]
        if len(set(ints)) == len(ints) and sorted(ints) == list(range(min(ints), max(ints) + 1)):
            return f"{min(ints)}..{max(ints)}" if len(ints) > 1 else f"{{{ints[0]}}}"
    return "{" + ", ".join(show_value(value, world) for value in domain) + "}"


def show_scope(scope: dict, params: list[dict], world: str = "integer@1") -> str:
    """Show exact domains, or enumerate non-product input tuples explicitly."""
    if "domains" in scope:
        domains = scope["domains"]
    else:
        inputs = scope["inputs"]
        if not inputs:
            return "∅"
        domains = [list(dict.fromkeys(json.dumps(row[index], sort_keys=True) for row in inputs))
                   for index in range(len(inputs[0]))]
        domains = [[json.loads(value) for value in domain] for domain in domains]
        product = {tuple(json.dumps(value, sort_keys=True) for value in row)
                   for row in itertools.product(*domains)}
        actual = {tuple(json.dumps(value, sort_keys=True) for value in row) for row in inputs}
        if product != actual or len(inputs) != len(actual):
            names = ", ".join(param["name"] for param in params)
            values = ", ".join("(" + ", ".join(show_value(value, world) for value in row) + ")"
                                for row in inputs)
            return f"({names}) ∈ {{{values}}}"
    return ", ".join(f"{param['name']} ∈ {_domain(domain, param, world)}"
                     for param, domain in zip(params, domains))


def show_examples(examples: list[dict], operator: str, params: list[dict],
                  world: str = "integer@1") -> str:
    """Use the published definition's left-hand side as the notation template."""
    lhs = operator.split("=", 1)[0].strip()
    names = [param["name"] for param in params]
    if not lhs or not all(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", lhs) for name in names):
        lhs = f"{operator}({', '.join(names)})"
    lines = []
    for example in examples:
        values = {param["name"]: show_value(value, world)
                  for param, value in zip(params, example["inputs"])}
        expression = re.sub(r"(?<!\w)(?:" + "|".join(map(re.escape, values)) + r")(?!\w)",
                            lambda match, replacements=values: replacements[match.group()], lhs) if values else lhs
        lines.append(f"{expression} = {show_value(example['output'], world)}")
    return "\n".join(lines)
