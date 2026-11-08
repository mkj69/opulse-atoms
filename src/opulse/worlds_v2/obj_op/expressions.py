"""Run the design's ASCII object literals through the Opulse kernel."""

from opulse.atoms import kernel, notation
from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Card, Ok, Unknown


def expression(source, library=None):
    def lower(node):
        if isinstance(node, n.Lit) and isinstance(node.value, tuple):
            items = n.Lit(())
            for item in reversed(node.value):
                items = n.Call("cons", (lower(n.Lit(item)), items))
            return items
        if isinstance(node, n.Lit) and isinstance(node.value, Card):
            value = node.value
            arguments = tuple(lower(n.Lit(field)) for field in value.fields)
            if value.sort == "Band":
                return n.Call("band", arguments)
            if value.sort == "Cycle":
                return n.Case(((n.Test(n.Call("lt", (n.Lit(0), arguments[1]))),
                                n.Call("Cycle.make", (n.Call("cycle_raw", arguments),))),),
                              n.Call("mod", arguments))
            if value.sort == "Plan":
                items = n.Lit(())
                for argument in reversed(arguments):
                    items = n.Call("cons", (argument, items))
                return n.Case(((n.Test(n.Call("le", (n.Lit(1), n.Call("list_length", (items,))))),
                                n.Case(((n.Test(n.Call("le", (n.Call("list_length", (items,)), n.Lit(32)))),
                                         n.Call("Plan.make", (n.Call("plan_raw", (items,)),))),),
                                       n.Lit(Bottom("plan_size")))),), n.Lit(Bottom("plan_size")))
            if value.sort == "Window":
                return n.Case(((n.Test(n.Call("le", (arguments[1], arguments[2]))),
                                n.Call("Window.make", (n.Call("window_raw", (
                                    *arguments, n.Call("compile", (arguments[0],)))),))),),
                              n.Lit(Bottom("window_order")))
            if value.sort == "Blackout":
                items = n.Lit(())
                for argument in reversed(arguments[1:]):
                    items = n.Call("cons", (argument, items))
                return n.Call("Blackout.make", (n.Call("blackout_raw", (arguments[0], items)),))
            raise ValueError(f"unknown object literal {value.sort}")
        if isinstance(node, n.Call):
            return n.Call(node.fn, tuple(lower(argument) for argument in node.args))
        return node

    return lower(notation.parse_expr(source, library))


def calls_in(text, name="clear_hit"):
    """Extract complete calls from narrative prompts, ignoring prose punctuation."""
    import re

    for match in re.finditer(r"\b" + re.escape(name) + r"\(", text):
        depth = 0
        for position in range(match.start() + len(name), len(text)):
            if text[position] == "(":
                depth += 1
            elif text[position] == ")":
                depth -= 1
                if depth == 0:
                    yield text[match.start():position + 1]
                    break


def run(library, source, trace=False):
    return kernel.evaluate(expression(source, library), scope=library.scope(), limits=kernel.Limits(fuel=4_000_000),
                           trace=trace)


def display(outcome):
    if isinstance(outcome, Bottom):
        return f"Bottom({outcome.reason})"
    if isinstance(outcome, Unknown):
        return f"Unknown({outcome.resource})"
    value = outcome.value
    if isinstance(value, Card):
        if value.sort == "Cycle":
            residue, period = value.fields[0].fields
            return f"Cycle<{residue}, {period}>"
        if value.sort == "Plan":
            return "Plan<" + ", ".join(display(Ok(cycle)) for cycle in value.fields[0].fields[0]) + ">"
        if value.sort == "Window":
            plan, lo, hi, _ = value.fields[0].fields
            return f"Window<{display(Ok(plan))}, {lo}, {hi}>"
        if value.sort == "Blackout":
            window, bands = value.fields[0].fields
            suffix = "".join(f", Band<{band.fields[0]}, {band.fields[1]}>" for band in bands)
            return f"Blackout<{display(Ok(window))}{suffix}>"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
