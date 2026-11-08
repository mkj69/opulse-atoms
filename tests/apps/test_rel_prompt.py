"""Legacy relation answers must follow from the public prompt alone."""

import json
import re
from itertools import islice

import pytest

from opulse.apps import make


def solve_relation_prompt(prompt):
    table_lines = [line.removeprefix("Relation table (JSON): ")
                   for line in prompt.splitlines() if line.startswith("Relation table (JSON): ")]
    assert len(table_lines) == 1
    table = json.loads(table_lines[0])
    assert set(table["relations"]) == {"parent", "colleague", "neighbour"}
    assert set(table["entities"]) >= set(table["relations"]["colleague"])

    definitions_text = prompt.split("Definitions: ", 1)[1].split("\nRelation table", 1)[0]
    assert definitions_text.endswith(".")
    definitions = {name: (bool(binary), body) for name, binary, body in re.findall(
        r"a (f\d+)( b)? = \{ (.*?) \}(?=;|$)", definitions_text[:-1])}
    assert definitions
    expression = prompt.split("Expression: ", 1)[1].split(". Initial input:", 1)[0]
    tokens_pattern = r'"[^"\n]*"|-?\d+|[A-Za-z_][A-Za-z_0-9]*|[()+-]'

    def evaluate(expression_text, entity=None, count=None):
        tokens = re.findall(tokens_pattern, expression_text)
        assert re.fullmatch(rf"(?:{tokens_pattern}|\s)+", expression_text), expression_text
        position = 0

        def atom():
            nonlocal position
            token = tokens[position]
            position += 1
            if token == "(":
                value = chain()
                assert tokens[position] == ")"
                position += 1
                return value
            if token.startswith('"'):
                return json.loads(token)
            if token.lstrip("-").isdigit():
                return int(token)
            assert token in ("a", "b"), token
            return entity if token == "a" else count

        def apply(operator, left, right=None):
            if left is None or (right is None and operator == "rel_equal"):
                return None
            if operator.startswith("rel_"):
                if operator == "rel_equal":
                    return left == right
                return table["relations"][operator[4:]].get(left)
            binary, body = definitions[operator]
            if binary:
                assert right is not None
            else:
                assert right is None
            if body.startswith("a, if b == 0; "):
                recursive = re.fullmatch(
                    rf"a, if b == 0; \(a {operator} \(b - 1\)\) (f\d+), if b > 0 and b <= 8; "
                    rf"\(a {operator} \(b \+ 1\)\) \1, if b < 0 and b >= - 8", body)
                assert recursive and -8 <= right <= 8
                result = left
                for _ in range(abs(right)):
                    result = apply(recursive[1], result)
                return result
            chosen, separator, remaining = body.partition(", if a rel_equal ")
            if separator:
                target, separator, alternative = remaining.partition("; ")
                assert separator and alternative.endswith(", else")
                body = chosen if left == json.loads(target) else alternative.removesuffix(", else")
            return evaluate(body, left, right)

        def chain():
            nonlocal position
            value = atom()
            while position < len(tokens) and tokens[position] != ")":
                operator = tokens[position]
                position += 1
                if operator == "-":
                    value -= atom()
                else:
                    assert operator in definitions or operator in (
                        "rel_parent", "rel_colleague", "rel_neighbour", "rel_equal")
                    binary = operator == "rel_equal" or (operator in definitions and definitions[operator][0])
                    value = apply(operator, value, atom() if binary else None)
            return value

        result = chain()
        assert position == len(tokens), expression_text
        return result

    return evaluate(expression)


@pytest.mark.parametrize("angle", ("compute", "invert", "decide", "describe", "induce", "create"))
@pytest.mark.parametrize("level", range(1, 6))
def test_legacy_relation_prompt_has_enough_facts_to_solve(angle, level):
    stream = make("rel", level=level, angle=angle)
    if angle != "compute":
        with pytest.raises(ValueError, match="legacy published data supports compute only"):
            next(stream)
        return

    for task in islice(stream, 8):
        assert task["prompt"].isascii()
        assert solve_relation_prompt(task["prompt"]) == task["_grading"]["task"]["answer"]
