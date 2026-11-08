"""Challenge v2 export invariants (docs/spec/atoms-v2.md, section 12)."""

import json
import re
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.tasks_v2 import kernel_engine, lawbridge
from opulse.tasks_v2.challenge_grade import grade_entry, grade_reference
from opulse.tasks_v2.difficulty import Features, measure
from opulse.tasks_v2.task import ANGLES, KINDS, Task

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from tasks_v2_challenge import (
    SOURCE_KINDS,
    _check_bridge_interface,
    _check_rewrite,
    _closure,
    _private_path,
    _prompt,
    _purpose,
    _shape,
    _trivial,
)


def test_frozen_ladders_regrade_and_are_distinct(challenge_grading):
    data = json.loads((ROOT / 'docs/assets/data/challenge/v2.json').read_text())
    grading = challenge_grading
    assert data['schema'] == 'opulse.challenge_v2/3'
    assert data['challenges'] == []
    assert set(data['ladders']) == set(ANGLES)
    assert sum(map(int, data['distribution'].values())) >= 48
    ids, closures, shapes, purposes = set(), set(), set(), set()
    assert {entry['kind'] for entries in data['ladders'].values() for entry in entries} == set(SOURCE_KINDS)
    for angle, entries in data['ladders'].items():
        counts = Counter(entry['level'] for entry in entries)
        assert all(counts[level] >= 2 for level in range(2, 6))
        assert any('/template/' in entry['id'] for entry in entries)
        assert any('/template/' in entry['id'] and
                   (entry['angle'] in ('induce', 'create') or
                    'arguments' in grading[entry['id']]['task']['question']) for entry in entries)
        assert any(entry['kind'] in ('law', 'bridge') for entry in entries)
        if angle == 'compute':
            assert any(entry['world'] == 'computer@1' for entry in entries)
        assert len({entry['kind'] for entry in entries}) >= 4 and set(SOURCE_KINDS) <= set(KINDS)
        assert entries[0]['level'] >= 3
        first_features = measure(Task.from_dict(grading[entries[0]['id']]['task']))
        assert first_features.failures or (first_features.depth >= 2 and first_features.definitions >= 3)
        for entry in entries:
            assert {'id', 'world', 'kind', 'angle', 'level', 'purpose', 'label',
                    'prompt', 'answer_format', 'grading'} <= entry.keys()
            assert entry['grading'] == 'Graded offline by the exact grader.'
            assert 'reference' not in entry and 'grader' not in entry
            assert entry['angle'] == angle
            assert entry['label'] in ('atoms-v2', 'legacy-v1 operations world')
            task = Task.from_dict(grading[entry['id']]['task'])
            features = measure(task)
            assert entry['level'] == features.level
            assert grade_reference(task, grading[entry['id']]['reference'])
            assert not _trivial(task)
            assert entry['prompt'] == _prompt(task)
            assert entry['purpose'] == _purpose(task, features)
            for value, collection in ((entry['id'], ids), (_closure(task), closures),
                                      (_shape(task), shapes), (entry['purpose'], purposes)):
                assert value not in collection
                collection.add(value)
            assert all(ord(character) < 128 for character in json.dumps(entry, ensure_ascii=False))
            assert entry['purpose'].endswith('.') and '\n' not in entry['purpose']
            assert not re.search(r'value response|linked rules|scoped cases|base steps|shown definitions',
                                 entry['purpose'], re.IGNORECASE)
            assert json.dumps(grading[entry['id']]['reference'], ensure_ascii=True) not in entry['purpose']
            if entry['world'] == 'computer@1':
                assert '"node"' not in entry['prompt']
            assert not re.search(r'\b[a-z]\s+[$&#%@\u2666]\s+[a-z]\b',
                                 entry['prompt'])
    assert 'four_kinds' not in data['paths']
    path = data['paths']['six_kinds_one_world']
    assert path['world'] == 'integer@1'
    assert {step['kind'] for step in path['steps']} == set(SOURCE_KINDS)
    seen = set()
    # No literal answers here (R16-T-1; integration round 5): the build-time references must match a
    # fresh recomputation from code, have the shape of their kind, and grade correct offline.
    recomputed = {item['id']: item['reference'] for item in _private_path()}
    shapes = ('fraction', 'fraction', 'fraction', 'bool', 'fraction', 'int')
    for step, shape in zip(path['steps'], shapes, strict=True):
        reference = grading[step['id']]['reference']
        assert reference == recomputed[step['id']]
        assert set(reference) == {'ok'} and reference['ok']['t'] == shape
        assert grade_entry(step['id'], reference)['correct']
        assert not grade_entry(step['id'], {'bottom': 'invalid'})['correct']
    law_step, bridge_step = path['steps'][3:5]
    assert bridge_step['depends_on'] == ['fraction']
    assert 'sum_twice_rewrite' not in bridge_step['definition']
    assert 'verification' not in law_step and 'verification' not in bridge_step
    law_evidence = grading[law_step['id']]['verification']
    bridge_evidence = grading[bridge_step['id']]['verification']
    assert len(law_evidence['scope']) == 9
    assert law_evidence['method'] == 'bounded'
    assert bridge_evidence['method'] == 'bounded'
    assert bridge_evidence['interface'] == [['pair_add', 'frac_add']]
    assert len(bridge_evidence['scope']) == 4
    for step in path['steps']:
        assert step['world'] == path['world']
        assert set(step['depends_on']) <= seen
        assert bool(step['depends_on']) == bool(seen)
        assert all(name in step['definition'] for name in step['depends_on'])
        assert set(step['depends_on']) <= nodes.references(nodes.from_json(step['body']))
        assert grade_entry(step['id'], grading[step['id']]['reference']) == {'correct': True}
        seen.add(step['name'])


def _assert_no_public_checks(value, private_answer=None):
    if private_answer is not None:
        assert json.dumps(private_answer, ensure_ascii=True) not in json.dumps(value, ensure_ascii=True)
    forbidden = {'reference', 'grader', 'verification', 'check', 'hash', 'hashes', 'features',
                 'outcome', 'solution', 'solutions', 'answer', 'native_task_b64', 'digest'}
    if isinstance(value, dict):
        assert not forbidden & value.keys()
        for item in value.values():
            _assert_no_public_checks(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_public_checks(item)
    elif isinstance(value, str):
        assert not re.search(r'(?i)\b[a-f0-9]{64}\b', value)


def test_path_law_and_bridge_reject_false_obligations():
    fraction = kernel_engine.fraction
    lhs = nodes.Call('add', (nodes.Var('x'), nodes.Var('y')))
    rhs = nodes.Call('add', (nodes.Var('y'), nodes.Var('x')))
    scope = ((2, 3), (4, 7))
    _check_rewrite(lambda expression: kernel_engine.run('integer@1', expression).outcome.value,
                   lhs, rhs, scope)
    with pytest.raises(ValueError, match='path law fails'):
        _check_rewrite(lambda expression: kernel_engine.run('integer@1', expression).outcome.value,
                       lhs, nodes.Var('x'), scope)
    bridge = replace(lawbridge.bridges()['pair_to_frac'], map=nodes.Call('fraction', (
        nodes.Call('fraction_canon', (nodes.Var('x'),)),)))
    assert lawbridge.check_bridge(bridge)
    assert len(_check_bridge_interface(bridge, lambda expression: lawbridge.evaluate(
        expression).value)) == 4
    with pytest.raises(ValueError, match='authored operation'):
        _check_bridge_interface(bridge, lambda expression: fraction(1, 2))
    assert not lawbridge.check_bridge(replace(bridge, map=nodes.Lit(fraction(1, 2))))


@given(st.integers(-20, 20), st.integers(-20, 20))
@settings(max_examples=12, deadline=None)
def test_path_rewrite_scope_is_checked_for_each_assignment(left, right):
    lhs = nodes.Call('add', (nodes.Var('x'), nodes.Var('y')))
    rhs = nodes.Call('add', (nodes.Var('y'), nodes.Var('x')))
    _check_rewrite(lambda expression: kernel_engine.run('integer@1', expression).outcome.value,
                   lhs, rhs, ((left, right),))


def test_public_entries_have_no_answer_checks_and_offline_grader_rejects_perturbations(challenge_grading):
    path = ROOT / 'docs/assets/data/challenge/v2.json'
    public_text = path.read_text()
    assert '"reference"' not in public_text and 'native_task_b64' not in public_text
    data = json.loads(public_text)
    grading = challenge_grading
    entries = [entry for ladder in data['ladders'].values() for entry in ladder]
    entries.extend(data['paths']['six_kinds_one_world']['steps'])
    for entry in entries:
        identifier = entry['id']
        answer = grading[identifier]['reference']
        assert entry['grading'] == 'Graded offline by the exact grader.'
        _assert_no_public_checks(entry, answer)
        assert grade_entry(identifier, answer) == {'correct': True}
        wrong = {'invalid': True} if isinstance(answer, dict) else (
            [] if isinstance(answer, list) else '<incorrect>')
        assert grade_entry(identifier, wrong) == {'correct': False}
    assert '"check"' not in public_text and '"hash"' not in public_text


def test_private_answer_payload_in_public_entry_is_rejected(challenge_grading):
    data = json.loads((ROOT / 'docs/assets/data/challenge/v2.json').read_text())
    grading = challenge_grading
    copied = deepcopy(data)
    entry = copied['paths']['six_kinds_one_world']['steps'][0]
    answer = grading[entry['id']]['reference']
    entry['answer_payload'] = answer
    with pytest.raises(AssertionError):
        _assert_no_public_checks(entry, answer)


def test_grader_cli_prints_json_verdict(challenge_grading):
    data = json.loads((ROOT / 'docs/assets/data/challenge/v2.json').read_text())
    identifier = data['paths']['six_kinds_one_world']['steps'][0]['id']
    answer = challenge_grading[identifier]['reference']
    command = [sys.executable, '-m', 'opulse.tasks_v2.challenge_grade', identifier, json.dumps(answer)]
    output = subprocess.check_output(command, cwd=ROOT, text=True)
    assert json.loads(output) == {'correct': True}
    assert json.loads(subprocess.check_output(command[:-1] + ['null'], cwd=ROOT, text=True)) == {'correct': False}


def test_score_thresholds_and_failure_work():
    for depth, expected_level in ((0, 1), (2, 2), (3, 3), (5, 3)):
        features = Features(depth, 0, 0, False, False, 0, 0, 0)
        assert features.level == expected_level
    assert Features(0, 0, 0, False, False, 0, 0, 0).score == 0
    assert Features(3, 3, 8, True, False, 1, 2, 1).level == 5
