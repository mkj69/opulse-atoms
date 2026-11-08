"""Loadable Git world and ten typed, checkable curriculum inventions."""

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Card
from opulse.atoms.world import WorldDecl

from . import model

TAGS = {
    "domain": "program", "modalities": ["text"],
    "open_kinds": ["object", "operation", "combinator", "observation"],
    "star_kind": "combinator", "reasoning": ["compute", "search", "planning", "inference"],
    "state": "stateful", "outcomes": "deterministic", "visibility": "full", "agents": 1,
    "scale": "2-8 commits, 1-3 text files, 10 invented definitions",
    "difficulty": "single disjoint edit to multi-commit conflicting replay",
    "uses": ["rl-training", "evaluation", "teaching", "experiment"],
}

_SCOPE = ("Regular UTF-8 LF line-based text files, no renames, symlinks, submodules, "
          "custom drivers, multiple best ancestors, or attributes; Git merge strategy ort.")

_STORY_USES = (
    "Represent a reviewable change with its preimage.",
    "Apply a guarded file edit, rejecting a stale preimage.",
    "Read paths touched by a change without exposing file contents.",
    "Fold guarded changes in order using a supplied series operation.",
    "Distinguish a clean merge from an unmerged worktree.",
    "Select a best common ancestor and reconcile both changed sides.",
    "Show unresolved index paths without changing the merge result.",
    "Replay first-parent patches, stopping at the first conflict.",
    "Reapply a linear topic onto a new base.",
    "Present history, diff and unresolved paths together.",
)

LADDER = (
    "1: One base commit, disjoint line edits; predict merged file.",
    "2: Same-line edits, insertions and deletion; predict markers and unmerged paths.",
    "3: Multiple paths, including independently edited files; distinguish path from hunk overlap.",
    "4: Two commits on each branch; use merge-base rather than the immediate parent.",
    "5: Three commits on each side; predict merge and replay, including first blocked commit.",
)


def _operation(name, inputs, output):
    return OperationSpec(name, "combine" if len(inputs) > 1 else "transform",
                         tuple(Edge(sort, name=param) for param, sort in inputs), Edge(output), name,
                         extra={"input_names": [param for param, _ in inputs]})


_GIVEN_OPERATIONS = (
    _operation("edit_atom", (("tree", "Tree"), ("edit", "Patch")), "Tree"),
    _operation("series_atom", (("tree", "Tree"), ("edits", "PatchList")), "Tree"),
    _operation("merge_atom", (("repo", "Repository"), ("ours", "str"), ("theirs", "str")), "MergeResult"),
    _operation("pick_atom", (("repo", "Repository"), ("onto", "str"), ("commits", "CommitList")), "MergeResult"),
    _operation("paths_probe", (("state", "TreePair"),), "PathList"),
    _operation("unmerged_probe", (("state", "MergeResult"),), "PathList"),
    _operation("review_probe", (("state", "ReviewInput"),), "Review"),
    _operation("valid_edit", (("value", "Patch"),), "bool"),
    _operation("valid_result", (("value", "MergeResult"),), "bool"),
    _operation("classify_atom", (("value", "MergeResult"),), "MergeReview"),
    _operation("edits_empty", (("edits", "PatchList"),), "bool"),
    _operation("edits_head", (("edits", "PatchList"),), "Patch"),
    _operation("edits_tail", (("edits", "PatchList"),), "PatchList"),
    _operation("edits_length", (("edits", "PatchList"),), "int"),
)

DECLARATION = WorldDecl(
    "real_git_merge", 1, "atoms-v2", {}, {},
    tuple(ObjectSpec(name, "given") for name in
          ("Path", "File", "MaybeFile", "Tree", "Commit", "Patch", "Conflict", "FileMerge",
           "PatchList", "PathList", "TreePair", "Repository", "MergeResult", "CommitList",
           "ReviewInput", "Review", "str")),
    _GIVEN_OPERATIONS,
    {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"},
    {"truth": "Repository", "judge_view": "full_state",
     "probes": [{"name": name} for name in ("paths_probe", "unmerged_probe", "review_probe")],
     "capabilities": {"learner": {"probes": "all"}}},
    {}, {"tags": TAGS, "scope": _SCOPE}, tuple(TAGS["open_kinds"]),
)
WORLD = DECLARATION.to_dict()
LAYER_ZERO = WORLD


def _defined_operation(name, inputs, output, call, arguments):
    body = nodes.Call(call, tuple(nodes.Var(argument) for argument in arguments))
    return Definition(name, "operation", "invented", 1, (call,),
                      _operation(name, inputs, output), body)


def _observation(name, probe):
    body = nodes.Call(probe, (nodes.Var("s"),))
    return Definition(name, "observation", "invented", 1, (probe,),
                      ObservationSpec(name, (probe,), body), body)


def _combinator(name, argument_names):
    remaining = nodes.Var("remaining")
    body = nodes.Rec("fold_edits", ("current", "remaining"),
                     nodes.Case(((nodes.Test(nodes.Call("edits_empty", (remaining,))),
                                  nodes.Var("current")),),
                                nodes.Call("fold_edits", (
                                    nodes.Call("step", (nodes.Var("current"),
                                                        nodes.Call("edits_head", (remaining,)))),
                                    nodes.Call("edits_tail", (remaining,))))),
                     tuple(nodes.Var(argument) for argument in argument_names),
                     nodes.Call("edits_length", (remaining,)))
    spec = CombinatorSpec(name, ("step", *argument_names), ("step",), body)
    return Definition(name, "combinator", "invented", 1,
                      ("edits_empty", "edits_head", "edits_tail", "edits_length"), spec, body)


DEFINITIONS = (
    Definition("Edit", "object", "invented", 1, ("valid_edit",),
               ObjectSpec("Edit", "refine", base="Patch",
                          valid=nodes.Call("valid_edit", (nodes.Var("x"),)), canon=nodes.Var("x")), None),
    _defined_operation("apply_edit", (("tree", "Tree"), ("edit", "Edit")),
                       "Tree", "edit_atom", ("tree", "edit")),
    _observation("changed_paths", "paths_probe"),
    _combinator("commit_series", ("tree", "edits")),
    Definition("MergeReview", "object", "invented", 1, ("valid_result", "classify_atom"),
               ObjectSpec("MergeReview", "refine", base="MergeResult",
                          valid=nodes.Call("valid_result", (nodes.Var("x"),)),
                          canon=nodes.Call("classify_atom", (nodes.Var("x"),))), None),
    _defined_operation("three_way", (("repo", "Repository"), ("ours", "str"),
                                        ("theirs", "str")), "MergeResult", "merge_atom",
                       ("repo", "ours", "theirs")),
    _observation("unmerged", "unmerged_probe"),
    _defined_operation("cherry_pick", (("repo", "Repository"), ("onto", "str"),
                                       ("commits", "CommitList")), "MergeResult", "pick_atom",
                       ("repo", "onto", "commits")),
    Definition("rebase", "operation", "invented", 2, ("cherry_pick",),
               _operation("rebase", (("repo", "Repository"), ("onto", "str"),
                                     ("commits", "CommitList")), "MergeResult"),
               nodes.Call("cherry_pick", (nodes.Var("repo"), nodes.Var("onto"),
                                          nodes.Var("commits")))),
    _observation("review", "review_probe"),
)

STORY = tuple({"lesson": index, "layer": definition.layer, "kind": definition.kind,
               "definition": definition, "use": usage}
              for index, (definition, usage) in enumerate(zip(DEFINITIONS, _STORY_USES), 1))


def build_library() -> Library:
    """Bind the declared layer-zero operations to the reference Git model."""
    implementations = (lambda tree, edit: model.apply_edit(
                           tree, edit.fields[0] if isinstance(edit, Card) else edit),
                       model.commit_series, model.merge, model.replay,
                       lambda pair: model.changed_paths(*pair), lambda result: result.conflicts,
                       lambda snapshot: model.Review(*snapshot),
                       lambda value: isinstance(value, model.Patch) and model.valid_path(value.path)
                       and model.valid_text(value.before) and model.valid_text(value.after)
                       and value.before != value.after,
                       model.valid_result, model.classify_result, lambda edits: not edits,
                       lambda edits: edits[0], lambda edits: edits[1:], len)
    atoms = [kernel.Atom(spec.name, len(spec.inputs), implementation,
                         kind="observation" if spec.name.endswith("_probe") else "operation")
             for spec, implementation in zip(_GIVEN_OPERATIONS, implementations)]
    return Library(DECLARATION, atoms)


def promote_curriculum() -> Library:
    """Check, unfold, verify and promote the bounded ten-definition Git lesson."""
    repo = model.Repository()
    repo.add("base", (), {"a": "zero\n"})
    repo.add("main", ("base",), {"a": "zero\n", "b": "main\n"})
    repo.add("topic", ("base",), {"a": "topic\n"})
    result = model.merge(repo, "main", "topic")
    edit = model.Patch("a", "zero\n", "topic\n")
    snapshot = (("main", "base"), (edit,), ())
    samples = {
        "Edit": ((edit,), None),
        "apply_edit": (({"a": "zero\n"}, edit), model.apply_edit),
        "changed_paths": ((({"a": "zero\n"}, {"a": "topic\n"}),),
                          lambda pair: model.changed_paths(*pair)),
        "commit_series": ((kernel.FnRef("apply_edit"), {"a": "zero\n"}, (edit,)), None),
        "MergeReview": ((result,), None),
        "three_way": ((repo, "main", "topic"), model.merge),
        "unmerged": ((result,), lambda value: value.conflicts),
        "cherry_pick": ((repo, "main", ("topic",)), model.replay),
        "rebase": ((repo, "main", ("topic",)), model.rebase),
        "review": ((snapshot,), lambda value: model.Review(*value)),
    }
    library = build_library()
    for definition in DEFINITIONS:
        library.write(definition)
        library.check(definition.name)
        sample, reference = samples[definition.name]
        library.make_callable(definition.name, (sample,))
        family = (sample[0].name,) if definition.kind == "combinator" else ()
        scope = {"domain": f"bounded one Git example for {definition.name}", "size": 1}
        if family:
            scope["op_family"] = list(family)
        request = VerifyRequest("bounded", (sample[1:] if family else sample,), scope,
                                reference=reference, extra={"op_family": family} if family else {})
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract(f"{definition.name} on the recorded bounded scope"))
    return library
