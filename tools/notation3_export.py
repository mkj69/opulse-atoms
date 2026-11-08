"""Stamp and verify notation-v3 lookup blocks on site exports."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from opulse.notation3.export import notation3_block

DATA = ROOT / 'docs/assets/data'
# Only data that site pages render gets a block; gen_v2 and meta exports are not shown.
FAMILIES = ('worlds_v2', 'atoms2')
CHALLENGE = ROOT / 'docs/assets/data/challenge/v2.json'
DESIGNS = ROOT / 'docs/worlds/designs.json'
DATA_JS = ROOT / 'docs/assets/js/atoms2/data.js'
RESEARCH_EXPORT = ROOT / 'docs/research/bundles/action-audit-v1/action-export.json'


def targets(only=None):
    paths = [path for family in FAMILIES for path in (DATA / family).rglob('*.json')
             if path != DATA / 'atoms2/parse_status.json']
    paths.append(CHALLENGE)
    paths.append(DESIGNS)
    paths.append(DATA_JS)
    paths.append(RESEARCH_EXPORT)
    return [path for path in sorted(paths) if only is None or
            fnmatch.fnmatch(path.relative_to(ROOT).as_posix(), only) or
            fnmatch.fnmatch(path.name, only)]


def _append_json(raw, block, *, indent=None, ensure_ascii=True):
    newline = '\n' if raw.endswith('\n') else ''
    trimmed = raw.rstrip()
    if not trimmed.endswith('}'):
        raise ValueError('expected a JSON object')
    if indent is None:
        separator = ',' if len(trimmed) > 2 else ''
        return trimmed[:-1] + separator + '"notation3":' + json.dumps(
            block, ensure_ascii=ensure_ascii, separators=(',', ':')) + '}' + newline
    space = ' ' * indent
    payload = json.dumps(block, indent=indent, ensure_ascii=ensure_ascii)
    payload = payload.replace('\n', '\n' + space)
    separator = ',' if trimmed[:-1].rstrip().endswith('"') or len(trimmed[:-1].strip()) > 1 else ''
    return trimmed[:-1].rstrip() + separator + '\n' + space + '"notation3": ' + payload + '\n}' + newline


def stamped(path, *, report=None):
    text = path.read_text(encoding='utf-8')
    if path == DATA_JS:
        prefix, remainder = text.split('A2.kernelData=', 1)
        data_text, suffix = remainder.split(';', 1)
        data = json.loads(data_text)
        data.pop('notation3', None)
        baseline = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        source = 'data.js'
        block = notation3_block(data, 'data_js', source=source, report=report)
        data['notation3'] = block
        payload = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        return prefix + 'A2.kernelData=' + payload + ';' + suffix, block, len(payload.encode()) - len(baseline.encode())
    data = json.loads(text)
    data.pop('notation3', None)
    family = ('worlds_v2' if path == RESEARCH_EXPORT else 'designs' if path == DESIGNS
              else path.relative_to(DATA).parts[0])
    source = (path.relative_to(DATA / family).as_posix()
              if family == 'gen_v2' else
              path.relative_to(DATA).as_posix() if family == 'atoms2' else None)
    block = notation3_block(data, family, source=source, report=report)
    indent_match = re.search(r'\n( +)"', text)
    indent = len(indent_match[1]) if indent_match else None
    ensure_ascii = not any(ord(char) > 127 for char in text)
    if list(data) == sorted(data):
        baseline = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii,
                              sort_keys=True, separators=(',', ':') if indent is None else None)
        data['notation3'] = block
        rendered = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii,
                              sort_keys=True, separators=(',', ':') if indent is None else None)
        return (rendered + ('\n' if text.endswith('\n') else ''), block,
                len(rendered.encode()) - len(baseline.encode()))
    if indent is None:
        original = json.dumps(data, ensure_ascii=ensure_ascii, sort_keys=True,
                              separators=(',', ':'))
    else:
        original = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii,
                              sort_keys=False)
        marker = '\n' + ' ' * indent + '"notation3":'
        if marker in text:
            original = text[:text.index(marker)].rstrip().rstrip(',') + '\n}'
        else:
            original = text.rstrip()
    if text.endswith('\n'):
        original += '\n'
    rendered = _append_json(original, block, indent=indent, ensure_ascii=ensure_ascii)
    return rendered, block, len(rendered.encode()) - len(original.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--only', metavar='GLOB')
    parser.add_argument('--report', action='store_true', help='list skipped machine texts with reasons')
    args = parser.parse_args()
    counts = defaultdict(lambda: [0, set(), 0, 0, 0, 0])
    world_counts = defaultdict(int)
    stale = []
    skipped_report = [] if args.report else None
    for path in targets(args.only):
        try:
            rendered, block, growth = stamped(path, report=skipped_report)
        except (ValueError, KeyError, TypeError) as error:
            print(f'{path.relative_to(ROOT)}: {error}', file=sys.stderr)
            return 1
        current = path.read_text(encoding='utf-8')
        family = ('data_js' if path == DATA_JS else 'research' if path == RESEARCH_EXPORT
                  else 'designs' if path == DESIGNS else path.relative_to(DATA).parts[0])
        row = counts[family]
        row[0] += 1
        row[1].update(block['worlds'])
        row[2] += sum(len(world['formulas']) for world in block['worlds'].values())
        row[3] += sum(len(world['prose']) for world in block['worlds'].values())
        row[4] += sum(world['skipped'] for world in block['worlds'].values())
        for world, entry in block['worlds'].items():
            world_counts[world] += entry['skipped']
        row[5] += growth
        if rendered != current:
            stale.append(path.relative_to(ROOT).as_posix())
            if not args.check:
                path.write_text(rendered, encoding='utf-8')
    for family, (files, worlds, formulas, prose, skipped, growth) in sorted(counts.items()):
        print(f'{family}: {files} files, {len(worlds)} worlds, {formulas} formulas, '
              f'{prose} prose, {skipped} skipped, {growth / 1_000_000:.3f} MB growth')
    if skipped_report is not None:
        for world, count in sorted(world_counts.items()):
            print(f'{world}: {count} skipped')
        for world, key, text, reason in skipped_report:
            print(f'{world}\t{key}\t{text}\t{reason}')
    if args.check and stale:
        print('stale: ' + ', '.join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
