"""Declared judge projections (spec section 7.1, invariant 3)."""

from dataclasses import replace

import pytest

from opulse.tasks_v2.angles.object import generate
from opulse.tasks_v2.angles.operation import generate as generate_operation
from opulse.tasks_v2.task import ANGLES, METHODS, SHAPES, Task


@pytest.mark.parametrize("angle", ANGLES)
def test_declared_projection_accepted_for_each_grader_method(angle):
    original = generate("compute", 0, 0)
    shape = SHAPES[angle][0]
    task = replace(original, angle=angle, answer_shape=shape,
                   variant="one_shot" if angle == "create" else None,
                   grader={**original.grader, "method": METHODS[shape]},
                   judge_view={"contract_projection": ["r0", "r2"]})
    assert Task.from_dict(task.to_dict()).judge_view == {"contract_projection": ["r0", "r2"]}


@pytest.mark.parametrize("fields", [[], ["r0", "r0"], [42], [""]])
def test_reject_invalid_projections(fields):
    with pytest.raises(ValueError, match="invalid judge view"):
        replace(generate("compute", 0, 0), judge_view={"contract_projection": fields})


def test_legacy_operation_grader_cannot_project_state():
    with pytest.raises(ValueError, match="cannot apply"):
        replace(generate_operation("integer", "compute"),
                judge_view={"contract_projection": ["r0"]})


@pytest.mark.parametrize("angle", ANGLES)
def test_computer_operation_can_declare_projection_for_every_angle(angle):
    task = generate("compute", 0, 0)
    shape = SHAPES[angle][0]
    projected = replace(task, world="computer@1", kind="operation", angle=angle,
                        answer_shape=shape, variant="one_shot" if angle == "create" else None,
                        grader={**task.grader, "method": METHODS[shape]},
                        judge_view={"contract_projection": ["r0"]})
    assert projected.judge_view == {"contract_projection": ["r0"]}
