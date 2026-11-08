"""Boundary unfold-equivalence checks (docs/spec/atoms-v2.md, sections 10 and 11 I2)."""

from __future__ import annotations

from dataclasses import dataclass

from opulse.atoms.boundary import Boundary, flatten_calls, legacy_expand
from opulse.trace import Reducer
from opulse.trace.tree import build_tree, flatten_view


@dataclass
class BoundaryCheck:
    ok: bool
    problems: list[str]


def unfold_equivalent(root_or_expression, *args) -> BoundaryCheck:
    """Check a kernel root with boundaries, or a legacy expression with its three tools.

    Legacy: ``(expression, registry, runtime, parser, boundaries)``;
    kernel: ``(root, boundaries)``.
    """
    if len(args) == 1:
        return unfold_equivalent_calls(root_or_expression, args[0])
    if len(args) == 4:
        return unfold_equivalent_legacy(root_or_expression, *args)
    raise TypeError("expected (root, boundaries) or (expression, registry, runtime, parser, boundaries)")


def _same_value(left, right) -> bool:
    return left is right or left == right


def unfold_equivalent_legacy(expression, registry, runtime, parser,
                             boundaries: list[Boundary]) -> BoundaryCheck:
    """Check each cut against the layer-0 derivation and, for pathless cuts, Reducer.

    Reducer's expand callback cannot represent positions, so path-selective views
    are checked against the derivation tree rather than a separate Reducer run.
    """
    problems = []
    try:
        root = build_tree(expression, registry, runtime, parser)
        full = flatten_view(root)

        def leaves(node):
            for item in node.steps:
                if item.child is None:
                    yield item.step
                else:
                    yield from leaves(item.child)

        reference = list(leaves(root))
        for index, boundary in enumerate(boundaries):
            try:
                view = flatten_view(root, expand_at=boundary.opens)
                if not _same_value(view[-1].step.expression_after.value if view else root.value, root.value):
                    problems.append(f"boundary {index}: final value differs")
                spliced = [step for visible in view for step in
                           (leaves(visible.child) if visible.child else (visible.step,))]
                if [(step.kind, step.operator.func_id, step.inputs, step.before, step.after,
                     step.reason) for step in spliced] != [
                        (step.kind, step.operator.func_id, step.inputs, step.before, step.after,
                         step.reason) for step in reference]:
                    problems.append(f"boundary {index}: unfolded base steps differ")
                if len(spliced) != len(full):
                    problems.append(f"boundary {index}: layer-0 step count differs")
                if not boundary.open_paths:
                    trace = Reducer(registry, runtime, parser, expand=legacy_expand(boundary),
                                    max_steps=max(2000, len(full) + 1)).reduce(expression)
                    if trace.truncated or [item.step for item in view] != trace.steps:
                        problems.append(f"boundary {index}: reducer trace differs")
            except (ValueError, AttributeError, RecursionError) as error:
                problems.append(f"boundary {index}: {error}")
    except (ValueError, AttributeError, RecursionError) as error:
        problems.append(f"derivation: {error}")
    return BoundaryCheck(not problems, problems)


def unfold_equivalent_calls(root, boundaries: list[Boundary]) -> BoundaryCheck:
    """Check that every view of one kernel call tree accounts for the same layer-0 steps.

    The kernel evaluates once, so outcomes cannot depend on a boundary; what can break is the
    view. For each boundary: the visible steps plus the jumps charged inside opened calls add
    up to ``root.steps``, and expanding every visible step gives the full given-atom sequence.
    Outcome equality of a definition and its unfolding is checked with ``kernel.inline``.
    """
    problems = []

    def atoms(node):
        if getattr(node, "fast", False) or node.given and not node.metered:
            return [node]
        return [atom for child in node.children for atom in atoms(child)]

    def own(node) -> int:
        return node.steps - sum(child.steps for child in node.children)

    try:
        reference = atoms(root)

        def check_structure(node):
            fast = getattr(node, "fast", False)
            if fast and not getattr(node, "fast_checked", False):
                problems.append(f"call tree: unchecked or incorrect fast path at {node.path}")
            if ((fast and (node.given or node.children or node.jumps or own(node) < 0)
                 or node.given and (own(node) < 0 or node.children and not node.metered
                                 or node.metered and (own(node) != 0 or node.jumps)))
                    or not node.given and not fast and own(node) != node.jumps):
                problems.append(f"call tree: inconsistent steps at {node.path}")
            for position, child in enumerate(node.children):
                if child.path != node.path + (position,):
                    problems.append(f"call tree: invalid path {child.path}")
                check_structure(child)

        check_structure(root)
        for index, boundary in enumerate(boundaries):
            try:
                visible, opened = _split(root, boundary)
                if [id(node) for node in visible] != [id(node) for node in flatten_calls(root, boundary)]:
                    problems.append(f"boundary {index}: flatten_calls disagrees with the tree walk")
                if sum(node.steps for node in visible) + sum(own(node) for node in opened) != root.steps:
                    problems.append(f"boundary {index}: layer-0 step count differs")
                if [id(atom) for node in visible for atom in atoms(node)] != [
                        id(atom) for atom in reference]:
                    problems.append(f"boundary {index}: given atom sequence differs")
            except (ValueError, AttributeError, RecursionError) as error:
                problems.append(f"boundary {index}: {error}")
    except (ValueError, AttributeError, RecursionError) as error:
        problems.append(f"call tree: {error}")
    return BoundaryCheck(not problems, problems)


def _split(root, boundary: Boundary) -> tuple[list, list]:
    """Visible steps and opened calls (the root counts as opened) of one view."""
    visible, opened, stack = [], [root], [iter(root.children)]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
        elif not getattr(child, "fast", False) and boundary.opens(child, child.path):
            opened.append(child)
            stack.append(iter(child.children))
        else:
            visible.append(child)
    return visible, opened
