"""Generated notation-v3 lookup blocks for published site data."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from opulse import notation3 as n3
from opulse.notation3 import convert as converter
from opulse.notation3 import legend as legends

FORMULA_KEYS = frozenset({
    'answer', 'outcome_text', 'display', 'ascii', 'decl', 'declaration', 'design_decl', 'design_text', 'symbol', 'call',
    'record_summary', 'definition', 'expression', 'memo_expression',
    'input', 'outcome', 'text', 'before', 'after', 'before_outcome',
    'after_outcome', 'diagram', 'example', 'result', 'grouping',
    'tree', 'postfix', 'value', 'title', 'inputs', 'output', 'rules',
    'prompt', 'attempt', 'probe', 'reading', 'form', 'notation',
})
# Keys that hold either a formula or a sentence; a sentence is simply not a formula.
PROSE_LIKE_KEYS = frozenset({'prompt', 'title', 'definition', 'form'})
PROSE_KEYS = frozenset({
    'prompt', 'answer', 'question', 'description', 'explanation',
    'design_text', 'text', 'title', 'summary', 'definition', 'hint',
})


def _worlds(data, family, source):
    if family == 'designs':
        return legends.atoms_from_designs(data)
    if family == 'worlds_v2' and 'world' in data:
        return {data['world']: legends.atoms_from_worlds_v2(data)[1]}
    if family == 'gen_v2' and 'world' in data:
        return {data['world']: legends.atoms_from_gen_v2(data)[1]}
    if family == 'gen_v2' and source:
        sibling = Path(__file__).resolve().parents[3] / 'docs/assets/data/gen_v2' / source.split('.', 1)[0]
        sibling = sibling.with_suffix('.json')
        if sibling.is_file():
            base = json.loads(sibling.read_text(encoding='utf-8'))
            if 'world' in base:
                combined = dict(base)
                combined.update(data)
                return {base['world']: legends.atoms_from_gen_v2(combined)[1]}
    if family == 'gen_v2' and isinstance(data.get('worlds'), dict):
        result = {}
        for name in sorted(data['worlds']):
            path = Path(__file__).resolve().parents[3] / 'docs/assets/data/gen_v2' / (name + '.json')
            if path.is_file():
                base = json.loads(path.read_text(encoding='utf-8'))
                result[base['world']] = legends.atoms_from_gen_v2(base)[1]
        return result
    if family == 'meta' and 'world' in data:
        return {data['world']: legends.atoms_from_meta(data)[1]}
    if family == 'atoms2' and source:
        name = source.rsplit('/', 1)[-1]
        result = legends.atoms_from_atoms2(name, data)
        if isinstance(result, dict):
            return result
        world = data.get('world', result[0])
        if world == name:
            world = {'walk.json': 'integer', 'grammar.json': 'grammar',
                     'checks.json': 'integer', 'computer.json': 'computer',
                     'grammar_core.json': 'grammar'}.get(name, name.removesuffix('.json'))
        try:
            atoms = legends.atoms_for_world(world)
        except (KeyError, OSError):
            atoms = []
        combined = {}
        for atom in (*atoms, *result[1]):
            combined.setdefault((atom.name, atom.kind), atom)
        return {world: list(combined.values())}
    if family == 'data_js':
        return legends.atoms_from_atoms2('data.js', data)
    identifiers = set()

    def discover(node):
        if isinstance(node, dict):
            world = node.get('world', node.get('source_world'))
            if isinstance(world, str):
                identifiers.add(world)
            for key, value in node.items():
                if key != 'notation3':
                    discover(value)
        elif isinstance(node, list):
            for value in node:
                discover(value)

    discover(data)
    if not identifiers and source:
        identifiers.add(source.rsplit('/', 1)[-1].split('.')[0])
    result = {}
    for identifier in sorted(identifiers):
        try:
            result[identifier] = legends.atoms_for_world(identifier)
        except (KeyError, OSError):
            result[identifier] = []
    # Cross-world records (bridges.json) define atoms of the world they start from.
    for item in data.get('story', ()) if isinstance(data, dict) else ():
        world = isinstance(item, dict) and item.get('world', item.get('source_world'))
        if world in result and item.get('name') and item.get('kind'):
            result[world] = [*result[world], legends.Atom(item['name'], item['kind'],
                                                          int(item.get('layer') or 1), 'invented')]
    return result


def notation3_block(data, family, *, source=None, report=None):
    """Build a block from only the unmodified machine export and its world legends."""
    if family not in {'worlds_v2', 'gen_v2', 'meta', 'atoms2', 'challenge', 'data_js', 'designs'}:
        raise ValueError(f'unknown export family: {family}')
    worlds = _worlds(data, family, source)
    candidates = defaultdict(lambda: {'formulas': {}, 'prose': set()})

    def visit(node, world, parent=''):
        if isinstance(node, dict):
            world = node.get('world', node.get('source_world', world))
            if world not in worlds:
                world = next(iter(worlds), None) if len(worlds) == 1 else None
            for key, value in node.items():
                if key == 'notation3':
                    continue
                if isinstance(value, str) and world is not None and not key.endswith('_zh'):
                    formula_field = key in FORMULA_KEYS and not (key == 'text' and parent not in {
                        'examples', 'example', 'outcome', 'showcase', 'steps', 'laws', 'bridges', 'story',
                        'declaration'})
                    # A 'name' that is a whole call (design cards name a run by its call text).
                    if formula_field or key == 'name' and any(char in value for char in '([{<'):
                        formulas = candidates[world]['formulas']
                        if key == 'design_decl' and value == node.get('design_text'):
                            formulas[value] = 'design_text'
                        elif value not in formulas or (formulas[value] in PROSE_LIKE_KEYS and
                                                     key not in PROSE_LIKE_KEYS):
                            formulas[value] = key
                    if key in PROSE_KEYS:
                        candidates[world]['prose'].add(value)
                elif isinstance(value, dict) and key in worlds and 'world' not in value:
                    visit(value, key, key)  # records keyed by their world id (data.js mode runs)
                else:
                    visit(value, world, key)
        elif isinstance(node, list):
            for value in node:
                visit(value, world, parent)
        elif isinstance(node, str) and world is not None and parent in FORMULA_KEYS:
            candidates[world]['formulas'].setdefault(node, parent)

    if family == 'designs':
        for world in data.get('worlds', {}):
            if legends.DESIGN_PREFIX + world in worlds:
                visit(data['worlds'][world], legends.DESIGN_PREFIX + world)
    else:
        default = data.get('world') if isinstance(data, dict) else None
        if default not in worlds:
            default = next(iter(worlds), None) if len(worlds) == 1 else None
        visit(data, default)
    result = {'version': 1, 'worlds': {}}
    if source is not None and family in ('atoms2', 'data_js'):
        result['source'] = source
    # A design record (atoms2 file whose source says so) proposes atoms; its texts are design
    # text and its dependency lists are not checked against the world's declarations.
    design_record = family == 'atoms2' and str(data.get('source', '')).startswith('Design record:')
    undeclared = []
    for world in sorted(worlds):
        if not design_record:
            try:
                legends.validate_dependencies(worlds[world], data)
            except ValueError as error:
                raise ValueError(f'world={world!r}: {error}') from error
        legend = legends.assign(worlds[world])
        context = converter.context_for(legend)
        formulas = {}
        skipped = 0
        designs = []
        for text in sorted(candidates[world]['formulas']):
            if design_record or (candidates[world]['formulas'][text] == 'design_text' and
                                 not converter.parseable_declaration(text, None)):
                designs.append(text)
                continue
            # Convert first: stored symbols such as '?count{...}' are outside the machine
            # grammar but have a display form; only texts that do not convert can be designs.
            try:
                formula = converter.convert_text(text, legend, context)
                if not _round_trips(formula['display'], formula['ascii']):
                    raise converter.ConversionError('v3 spelling does not round-trip')
                signature = formula['signature']
                if signature and not _round_trips(signature['display'], signature['ascii']):
                    raise converter.ConversionError('v3 signature does not round-trip')
                formulas[text] = formula
            except converter.UndeclaredAtom as error:
                if candidates[world]['formulas'][text] == 'design_text':
                    designs.append(text)
                    continue
                if candidates[world]['formulas'][text] in PROSE_LIKE_KEYS:
                    continue
                if (error.kind == 'object' and '<' in text and
                        not any(entry.atom.name == error.name and entry.atom.kind == 'object'
                                for entry in legend.entries) or
                        (family == 'designs' or text[:1] not in '?@~#') and
                        converter.is_design_text(text, context)):
                    designs.append(text)
                    continue
                undeclared.append(f'world={world!r} field={candidates[world]["formulas"][text]!r} '
                                  f'text={text!r} name={error.name!r} kind={error.kind!r}')
            except (converter.ConversionError, ValueError, KeyError, TypeError) as error:
                if candidates[world]['formulas'][text] == 'design_text':
                    designs.append(text)
                    continue
                if candidates[world]['formulas'][text] in PROSE_LIKE_KEYS:
                    continue  # a title or definition sentence, not a formula
                if converter.is_design_text(text, context):
                    designs.append(text)
                    continue
                skipped += 1
                if report is not None:
                    report.append((world, candidates[world]['formulas'][text], text, str(error)))
        prose = {}
        for text in sorted(candidates[world]['prose']):
            try:
                segments = converter.convert_prose(text, legend)
            except (converter.ConversionError, ValueError, KeyError, TypeError):
                continue
            if segments and any(segment[0] == 'f' for segment in segments) and all(
                    _round_trips(segment[1], segment[2]) for segment in segments
                    if segment[0] == 'f'):
                prose[text] = segments
        result['worlds'][world] = {'legend': legend.to_json(), 'formulas': formulas,
                                   'prose': prose, 'designs': designs, 'skipped': skipped}
    if undeclared:
        raise converter.ConversionError('undeclared atoms: ' + '; '.join(undeclared))
    return result


def _round_trips(display, ascii_text):
    try:
        return n3.to_ascii(display) == ascii_text and n3.to_display(ascii_text) == display
    except (ValueError, TypeError):
        return False


def add_notation3(data, family, *, source=None):
    """Append the generated block to an export without changing its existing fields."""
    # The block depends on the JSON content only (tuples and lists, key types), so a fresh
    # in-memory export and its serialized file give the same block.
    content = json.loads(json.dumps({key: value for key, value in data.items() if key != 'notation3'}))
    data['notation3'] = notation3_block(content, family, source=source)
    return data
