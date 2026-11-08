"""Structural difficulty checks for law, bridge, and template tasks (spec section 12)."""

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.tasks_v2.angles import bridge, law, template
from opulse.tasks_v2.difficulty import measure


def test_law_proof_features():
    sample = law.generate('create', 0, 0)
    features = measure(sample)
    assert features.rewrite_steps == 8
    assert features.variables == 2
    assert features.scope_size == len(sample.grader['scope']['assignments'])
    assert features.statement_depth >= 3
    assert features.saving == 4
    assert measure(law.generate('compute', 0, 0)).refused_steps == 1
    assert measure(law.generate('induce', 0, 0)).distinct_expressions >= 2


def test_bridge_diagram_features():
    sample = bridge.generate('invert', 0, 0)
    features = measure(sample)
    assert features.interface_pairs == len(sample.question['interface'])
    assert features.partial_domain
    assert features.map_depth >= 1
    assert features.candidate_bridges == len(sample.question['candidates'])
    assert features.scope_size == len(sample.grader['scope']['assignments'])
    assert not measure(bridge.generate('compute', 0, 3)).partial_domain


def test_template_family_features():
    sample = template.generate('create', 0, 1)
    features = measure(sample)
    assert features.parameters >= 1
    assert features.instantiations == len({sample.question['instance'], *(
        item['instance'] for item in sample.question['examples'] + sample.question.get('held_out', []))})
    assert features.expanded_depth >= 1
    assert features.obligations >= len(sample.question['examples'])
    assert features.obligations >= len(sample.question.get('held_out', []))


def test_hand_built_law_table_and_scope():
    sample = law.generate('induce', 0, 0)
    question = {**sample.question, 'examples': [['(0, 1)', '0', '0'],
                                                 ['(1, 2)', '1', '2']]}
    scope = {**sample.grader['scope'], 'assignments': [[0, 1], [1, 2]]}
    custom = replace(sample, question=question, grader={**sample.grader, 'scope': scope})
    features = measure(custom)
    assert features.distinct_expressions == 3
    assert features.scope_size == 2
    assert features.variables == 2


def test_hand_built_bridge_map_and_candidates():
    sample = bridge.generate('create', 0, 0)
    name = sample.question['name']
    shallow = replace(sample, question={**sample.question, 'candidates': ['left', 'right']},
                      reference={**sample.reference,
                                 'definition': f'bridge ~{name}: Byte -> Int = x'})
    deeper = replace(shallow, reference={**shallow.reference,
                             'definition': f'bridge ~{name}: Byte -> Int = increment(x)'})
    assert measure(shallow).candidate_bridges == 2
    assert measure(deeper).map_depth > measure(shallow).map_depth


def test_hand_built_template_body_and_obligations():
    sample = template.generate('create', 0, 0)
    body = sample.reference['definition']
    shallow = replace(sample, reference={**sample.reference,
                      'definition': {**body, 'body': {'rule': 'identity'}}},
                      question={**sample.question, 'examples': [], 'held_out': []},
                      grader={**sample.grader, 'scope': {'inputs': []}})
    deeper = replace(shallow, reference={**shallow.reference, 'definition':
                     {**body, 'body': {'nested': {'rule': 'identity'}}}},
                     question={**shallow.question, 'held_out': [{'instance': 'Extra'}]})
    assert measure(deeper).expanded_depth > measure(shallow).expanded_depth
    assert measure(deeper).obligations > measure(shallow).obligations
    assert measure(deeper).instantiations > measure(shallow).instantiations


@given(st.integers(min_value=0, max_value=15))
def test_extra_rewrite_never_reduces_difficulty(count):
    sample = law.generate('compute', 0, 1)
    expanded = replace(sample, question={**sample.question,
               'steps': sample.question['steps'] + [sample.question['steps'][0]] * count})
    assert measure(expanded).rewrite_steps == measure(sample).rewrite_steps + count
    assert measure(expanded).score >= measure(sample).score
    assert measure(expanded).level >= measure(sample).level


@settings(deadline=None)
@given(st.integers(min_value=0, max_value=15))
def test_extra_interface_pair_never_reduces_difficulty(count):
    sample = bridge.generate('compute', 0, 0)
    expanded = replace(sample, question={**sample.question,
               'interface': sample.question['interface'] + [sample.question['interface'][0]] * count})
    assert measure(expanded).interface_pairs == measure(sample).interface_pairs + count
    assert measure(expanded).score >= measure(sample).score
    assert measure(expanded).level >= measure(sample).level


def test_shipped_families_score_above_level_one():
    expected = {
        law: (5, 2, 3, 3, 4, 5),
        bridge: (4, 5, 4, 4, 4, 4),
        # Law/bridge template review added four bounded obligations to statement families.
        template: (3, 5, 5, 5, 5, 5),
    }
    for generator, levels in expected.items():
        for position, angle in enumerate(('compute', 'invert', 'decide', 'describe', 'induce', 'create')):
            sample = generator.generate(angle, 0, position * 16)
            assert measure(sample).level == levels[position], (generator.__name__, angle)
