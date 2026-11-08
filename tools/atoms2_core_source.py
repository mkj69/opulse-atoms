"""Report what the core notation printer can actually represent."""

from dataclasses import replace

from opulse.atoms.notation import parse_definition, print_definition
from opulse.atoms.spec import Cost
from tools.atoms2_parse_status import PLACEHOLDER_LABEL, placeholder_body


def printed_declaration(definition, library=None):
    bare = replace(definition, status="written", evidence=None, contract=None,
                   cost=Cost(), id=None)
    try:
        source = print_definition(bare, library)
    except (TypeError, ValueError) as error:
        return {"text": None, "reparses": False, "reason": str(error)}
    try:
        parsed = parse_definition(source, library)
        reparses = (parsed.kind, parsed.layer, parsed.body) == (bare.kind, bare.layer, bare.body)
        reason = None if reparses else "parsed definition differs from the core body"
        if placeholder_body(source):
            reparses, reason = False, PLACEHOLDER_LABEL
    except (TypeError, ValueError) as error:
        reparses, reason = False, str(error)
    return {"text": source, "reparses": reparses, "reason": reason}


def printed_label(result):
    if result["reason"] == PLACEHOLDER_LABEL:
        return PLACEHOLDER_LABEL
    return f"Printed from the core definition (re-parses: {'yes' if result['reparses'] else 'no'})"
