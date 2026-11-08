"""Printer failures do not erase printable core declarations."""

from dataclasses import replace
from unittest.mock import patch

from opulse.atoms.notation import parse_definition, print_definition
from opulse.atoms.spec import Cost
from opulse.worlds_v2.grammar.story import definitions as grammar_definitions
from opulse.worlds_v2.roads.story import definitions as roads_definitions
from tools.atoms2_core_source import printed_declaration, printed_label
from tools.atoms2_parse_status import PLACEHOLDER_LABEL


def test_printed_declaration_retains_actual_core_source():
    definition = next(item for item in roads_definitions() if item.name == "failures")
    result = printed_declaration(definition)
    assert result == {"text": print_definition(replace(definition, status="written", evidence=None,
                    contract=None, cost=Cost(), id=None)), "reparses": True, "reason": None}


def test_printed_placeholder_stays_visible_but_is_not_source():
    for text in ('obj Route = <raw: Int> where false L1',
                 'op temp(a: Int) -> Int = fail("pending") L1'):
        assert printed_declaration(parse_definition(text)) == {
            "text": text, "reparses": False, "reason": PLACEHOLDER_LABEL}
        assert printed_label(printed_declaration(parse_definition(text))) == PLACEHOLDER_LABEL


def test_printed_declaration_reports_reason_when_printer_cannot_print():
    definition = next(item for item in grammar_definitions() if item.name == "split")
    assert printed_declaration(definition) == {
        "text": None, "reparses": False,
        "reason": "operation metadata has no compact ASCII declaration"}


def test_parse_failure_keeps_exact_printed_text():
    definition = next(item for item in roads_definitions() if item.name == "failures")
    with patch("tools.atoms2_core_source.parse_definition", side_effect=ValueError("unsupported syntax")):
        result = printed_declaration(definition)
    assert result["text"] == print_definition(replace(definition, status="written", evidence=None,
                                                      contract=None, cost=Cost(), id=None))
    assert result["reparses"] is False
    assert result["reason"] == "unsupported syntax"


def test_research_does_not_present_nonrunnable_display_call():
    from pathlib import Path

    research = (Path(__file__).resolve().parents[1] / "docs/research/index.md").read_text()
    assert "apply(Doc<12:>" not in research
    assert "displayed call is not runnable parser source" in research
