"""SVG task views (docs/spec/atoms-v2.md, sections 7, 11 and 12).

These are observation renderers only. Grading always receives the original state.
SVG root data-fidelity declares whether the pictured state can be reconstructed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from html import escape

from opulse.atoms.notation import print_value
from opulse.atoms.values import Bottom, Card, Ok, Unknown, encode
from opulse.tasks_v2.hooks import show
from opulse.worlds import action
from opulse.worlds_v2.computer import machine

_LIMIT = 20_000
_PROBES = frozenset(("front_wall", "front_water", "front_colour", "front_height",
                     "holding", "held_colour"))
_BLOCK_COLORS = {"R": "#b33b45", "B": "#2477b9", "Y": "#b58510",
                 "G": "#28835a", "P": "#7957ae", "O": "#b75e24"}


def _svg(title: str, description: str, width: int, height: int, content: str,
         fidelity: str, shows: str) -> str:
    result = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
              f'width="{width}" height="{height}" role="img" data-fidelity="{fidelity}" '
              f'data-shows="{escape(shows, quote=True)}">'
              f'<title>{escape(title)}</title><desc>{escape(description)}</desc>{content}</svg>')
    if len(result.encode("utf-8")) >= _LIMIT:
        raise ValueError("SVG exceeds 20 KB")
    return result


def _probe_text(value: object, nan: object) -> str:
    """Probe readings: robot colours print as a quoted letter; other values in ASCII notation."""
    if value is nan:
        return "undefined"
    if isinstance(value, action.Colour):
        return json.dumps(str.__str__(value))  # the quoted colour letter, as before
    return show(value)


def _text(x: float, y: float, value: str, size: int = 12) -> str:
    return (f'<text x="{x}" y="{y}" fill="currentColor" '
            f'font-family="monospace" font-size="{size}">{escape(value)}</text>')


def _grid(x: int, y: int, columns: int, rows: int, cell_width: int, cell_height: int) -> str:
    right, bottom = x + columns * cell_width, y + rows * cell_height
    lines = [f'M{x + index * cell_width} {y}V{bottom}' for index in range(columns + 1)]
    lines += [f'M{x} {y + index * cell_height}H{right}' for index in range(rows + 1)]
    return f'<path d="{"".join(lines)}" stroke="currentColor" stroke-opacity=".25" fill="none"/>'


def render_robot(state: action.State, *, learner_view: bool = False,
                 probes: Iterable[str] = _PROBES) -> str:
    """Render all compact cells, or only the explicitly granted front/hand probes.

    Full view loses buried block colors and the stacking limit. Learner view also
    hides unprobed fields, other cells, coordinates and map dimensions.
    """
    if not isinstance(state, action.State):
        raise TypeError("expected action.State")
    if learner_view:
        granted = frozenset(probes)
        if granted - _PROBES:
            raise ValueError("unknown robot probe")
        front_x, front_y = state.front()
        readings = [(name, action.apply_atom(name, state)) for name in sorted(granted)]
        from opulse.core.semantics import NAN

        description = "\n".join(f"{name}: {_probe_text(value, NAN)}" for name, value in readings)
        description = "probes: " + (description if description else "none")
        cell = "?"
        if "front_wall" in granted and action.apply_atom("front_wall", state):
            cell = "#"
        elif "front_water" in granted and action.apply_atom("front_water", state):
            cell = "~"
        details = [f"front: {cell}"]
        if "front_height" in granted and state.inside(front_x, front_y):
            details.append(f"height: {len(state.stacks[state.index(front_x, front_y)])}")
        if "front_colour" in granted and state.inside(front_x, front_y):
            stack = state.stacks[state.index(front_x, front_y)]
            details.append(f"top: {stack[-1] if stack else 'undefined'}")
        if "holding" in granted:
            details.append(f"holding: {'yes' if state.held else 'no'}")
        if "held_colour" in granted:
            details.append(f"held colour: {state.held if state.held in action.COLOURS else 'undefined'}")
        content = ('<rect x="8" y="8" width="290" height="178" rx="8" '
                   'fill="#24a7bb" fill-opacity=".12"/>')
        content += _text(20, 36, "ROBOT PROBES")
        content += _text(20, 62, "->  front")
        content += "".join(_text(20, 84 + index * 18, line) for index, line in enumerate(details))
        return _svg("Robot probe view", description, 306, 194, content, "lossy",
                    "granted probe values only; no other cells or coordinates")

    cell_width = cell_height = 32
    width, height = state.width * cell_width + 32, state.height * cell_height + 32
    content = (f'<rect x="8" y="8" width="{width - 16}" height="{height - 16}" '
               'rx="8" fill="#24a7bb" fill-opacity=".1"/>')
    if state.width * state.height > 100:
        shows = ("all terrain, bridges, top block color and height, tools, robot facing and held item; "
                 "three-character cells; buried colors and max height omitted")
        content += _grid(16, 16, state.width, state.height, cell_width, cell_height)
        for row, line in enumerate(action.render_state(state).splitlines()[:-1]):
            cells = "".join(cell.ljust(3) for cell in line.split())
            content += (f'<text x="16" y="{32 + row * cell_height}" textLength="{state.width * cell_width}" '
                        'lengthAdjust="spacingAndGlyphs" font-family="monospace" font-size="11" '
                        f'fill="currentColor" dominant-baseline="central">{escape(cells)}</text>')
    else:
        shows = ("all terrain, bridges, top block color and height, tools, robot facing and held item; "
                 "buried colors and max height omitted; wall dark, water blue, bridge rails, "
                 "bench gold cell or B, tool T, stack swatch and height, "
                 "held block dot or gold tool dot")
        bridges = set(state.bridges)
        for row in range(state.height):
            for column in range(state.width):
                left, top = 16 + column * cell_width, 16 + row * cell_height
                center_x, center_y = left + 16, top + 16
                terrain = state.terrain[row][column]
                bridge = (column, row) in bridges
                fill = "#aeced7" if terrain == "~" else "#d8a234" if terrain == "B" else "#24a7bb"
                opacity = ".6" if terrain in ("~", "B") else ".06"
                content += (f'<rect data-cell="{column},{row}" x="{left}" y="{top}" '
                            f'width="32" height="32" fill="{fill}" fill-opacity="{opacity}" '
                            'stroke="currentColor" stroke-opacity=".28"/>')
                if terrain == "#":
                    content += (f'<rect x="{left + 7}" y="{top + 7}" width="18" height="18" '
                                'fill="currentColor" fill-opacity=".72"/>')
                if bridge:
                    content += (f'<path d="M{left + 4} {top + 11}h24m-24 10h24" '
                                'stroke="currentColor" stroke-width="2"/>')
                index = state.index(column, row)
                stack = state.stacks[index]
                if stack:
                    content += (f'<rect x="{left + 2}" y="{top + 2}" width="9" height="9" '
                                f'fill="{_BLOCK_COLORS[stack[-1]]}" stroke="currentColor" stroke-width=".5"/>')
                    content += (f'<text x="{center_x}" y="{center_y}" text-anchor="middle" '
                                'dominant-baseline="central" font-family="monospace" font-size="12" '
                                f'fill="currentColor">{len(stack)}</text>')
                elif state.tools[index] or terrain == "B":
                    content += (f'<text x="{center_x}" y="{center_y}" text-anchor="middle" '
                                'dominant-baseline="central" font-family="monospace" font-size="12" '
                                f'fill="currentColor">{"T" if state.tools[index] else "B"}</text>')
    robot_x, robot_y = state.robot
    center_x, center_y = 32 + robot_x * cell_width, 32 + robot_y * cell_height
    points = {"N": "0,-9 -8,8 8,8", "E": "9,0 -8,-8 -8,8",
              "S": "0,9 -8,-8 8,-8", "W": "-9,0 8,-8 8,8"}[state.facing]
    content += (f'<polygon points="{points}" transform="translate({center_x} {center_y})" '
                'fill="currentColor" stroke="#ffffff" stroke-width="1"/>')
    if state.held:
        held_fill = _BLOCK_COLORS[state.held] if state.held in action.COLOURS else "#d8a234"
        content += (f'<circle cx="{center_x + 11}" cy="{center_y + 11}" r="5" '
                    f'fill="{held_fill}" stroke="currentColor" stroke-width="1"/>')
    return _svg("Robot state", action.render_state(state), width, height, content, "lossy", shows)


def _shade(addresses: Iterable[int], fill: str, cell_width: int) -> str:
    selected = set(addresses)
    runs = []
    for row in range(16):
        column = 0
        while column < 16:
            if row * 16 + column not in selected:
                column += 1
                continue
            start = column
            while column < 16 and row * 16 + column in selected:
                column += 1
            left, top = 50 + start * cell_width, 98 + row * 18
            runs.append(f'M{left} {top}h{(column - start) * cell_width}v18h-{(column - start) * cell_width}z')
    return f'<path d="{"".join(runs)}" fill="{fill}" fill-opacity=".24"/>' if runs else ""


def render_computer(state: machine.State, highlights: Iterable[int] = ()) -> str:
    """Render every byte in decimal; highlighting does not change the state."""
    if not isinstance(state, machine.State):
        raise TypeError("expected computer State")
    selected = frozenset(highlights)
    if any(type(index) is not int or index not in range(256) for index in selected):
        raise ValueError("memory highlight must be an address from 0 to 255")
    cell_width, cell_height = 31, 18
    width, height = 50 + 16 * cell_width + 16, 98 + 16 * cell_height + 16
    content = (f'<rect x="8" y="8" width="{width - 16}" height="{height - 16}" rx="8" '
               'fill="#24a7bb" fill-opacity=".1"/>')
    content += _text(20, 31, "COMPUTER  /  MEMORY  16 x 16", 14)
    content += _text(20, 55, "  ".join(f"r{index}: {byte:03d}" for index, byte in enumerate(state.regs)))
    content += _text(20, 75, f"zero: {str(state.zero).lower()}   carry: {str(state.carry).lower()}")
    content += _shade((index for index, byte in enumerate(state.mem) if byte and index not in selected),
                      "#24a7bb", cell_width)
    content += _shade(selected, "#d8a234", cell_width)
    content += ('<defs><pattern id="memory-cell" x="50" y="98" width="31" height="18" '
                'patternUnits="userSpaceOnUse"><rect width="31" height="18" fill="none" '
                'stroke="currentColor" stroke-opacity=".25"/></pattern></defs>')
    content += ('<rect data-memory-table="true" data-cell-width="31" data-cell-height="18" '
                'x="50" y="98" width="496" height="288" fill="url(#memory-cell)"/>')
    content += ('<g fill="currentColor" font-family="monospace" font-size="11" '
                'text-anchor="middle" dominant-baseline="central">')
    for row in range(16):
        content += _text(24, 98 + row * cell_height + cell_height // 2, f"{row:02X}:", 11)
        content += f'<g transform="translate(50 {98 + row * cell_height})">'
        for column in range(16):
            left = column * cell_width
            content += f'<text x="{left + cell_width / 2}" y="9">{state.mem[row * 16 + column]:03d}</text>'
        content += '</g>'
    content += '</g>'
    description = show(machine.to_card(state))
    return _svg("Computer state", description, width, height, content, "lossless",
                "four registers, zero/carry flags, all 256 decimal bytes; highlighted addresses")


def render_value(value: object) -> str:
    """Print an arbitrary supported value verbatim as lossless text-in-image."""
    if isinstance(value, Ok):
        notation = f"Ok<{render_value_notation(value.value)}>"
    elif isinstance(value, Bottom):
        notation = f"Bottom<{print_value(value.reason)}>"
    elif isinstance(value, Unknown):
        notation = f"Unknown<{print_value(value.resource)}>"
    else:
        notation = render_value_notation(value)
    lines = [notation[index:index + 64] for index in range(0, len(notation), 64)] or [""]
    body = '<rect x="8" y="8" width="632" height="' + str(22 + len(lines) * 20) + '" rx="8" fill="#24a7bb" fill-opacity=".1"/>'
    body += "".join(_text(18, 37 + index * 20, line) for index, line in enumerate(lines))
    return _svg("Value", notation, 648, 38 + len(lines) * 20, body, "lossless",
                "exact ASCII notation of the value")


def render_value_notation(value: object) -> str:
    """Use unambiguous core notation, with a canonical JSON form for opaque Cards."""
    try:
        return print_value(value)
    except (TypeError, ValueError):
        if not isinstance(value, Card):
            raise
        return "ValueJSON<" + json.dumps(encode(value), ensure_ascii=True,
                                         sort_keys=True, separators=(",", ":")) + ">"
