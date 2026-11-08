"""Invented twelve-path version tower; all algorithms are kernel node trees."""

from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from itertools import product
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    compute_layer,
)
from opulse.atoms.values import Bottom, Card
from opulse.worlds_v2.versions import hosts
from opulse.worlds_v2.versions.world import new_library


@lru_cache(maxsize=1)
def reference():
    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/versions.py"
    spec = spec_from_file_location("versions_depth_reference", path)
    module = module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def lit(value):
    return n.Lit(value)


def var(name):
    return n.Var(name)


def call(name, *args):
    return n.Call(name, args)


def let(name, value, body):
    return n.Let(name, value, body)


def field(value, index):
    return call("field", value, lit(index))


def items(*values):
    result = lit(())
    for value in values:
        result = call("append", result, value)
    return result


def card(sort, *values):
    return call("card", lit(sort), lit(sort.lower()), items(*values))


def case(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def rec(fn, params, body, args, pending="pending"):
    return n.Rec(fn, params, body, args, call("length", var(pending)))


def patch(path, old, new):
    return call("Patch.patch", path, old, new)


def patch_field(value, index):
    return field(value, index)


def clashes(value):
    return field(value, 1)


def doc(value):
    return field(value, 0)


def delta_body():
    result = lit(())
    for path in reversed(hosts.PATHS):
        old = call("at", var("before"), lit(path))
        new = call("at", var("after"), lit(path))
        result = let("rest", result, case(call("eq", old, new), var("rest"),
                                          call("cons", patch(lit(path), old, new), var("rest"))))
    return let("before", call("read", var("before_doc")),
               let("after", call("read", var("after_doc")), card("Patches", result)))


def chain_body():
    body = case(call("is_empty", var("pending")), var("state"),
                let("step", call("head", var("pending")),
                    call("chain_loop", call("tail", var("pending")),
                         call("g", call("f", call("edit", var("state"),
                                 call("item_at", var("step"), lit(0)),
                                 call("item_at", var("step"), lit(1))))))))
    result = rec("chain_loop", ("pending", "state"), body, (var("steps"), var("start")))
    return let("result", result,
               let("changes", call("delta", var("start"), var("result")),
                   case(call("is_empty", field(var("changes"), 0)), var("start"), var("result"))))


def validate_body():
    path = patch_field(var("change"), 0)
    invalid = call("reject", lit("domain"))
    check = case(call("eq", call("sort_of", var("change")), lit("Patch")),
                 case(call("eq", call("tag", var("change")), lit("patch")),
                      case(call("lt", var("previous"), path),
                           case(call("eq", call("at", var("source"), path), patch_field(var("change"), 1)),
                                call("check_loop", call("tail", var("pending")), var("source"), path),
                                call("reject", lit("guard"))), invalid), invalid), invalid)
    loop = rec("check_loop", ("pending", "source", "previous"),
               case(call("is_empty", var("pending")), var("source"),
                    let("change", call("head", var("pending")), check)),
               (field(var("changes"), 0), var("document"), lit("")))
    return case(call("eq", call("sort_of", var("changes")), lit("Patches")),
                case(call("eq", call("tag", var("changes")), lit("patches")), loop, invalid), invalid)


def apply_body():
    next_step = let("change", call("head", var("pending")),
                    call("steps_loop", call("tail", var("pending")),
                         call("append", var("result"),
                              items(patch_field(var("change"), 0), patch_field(var("change"), 2)))))
    steps = rec("steps_loop", ("pending", "result"),
                case(call("is_empty", var("pending")), var("result"), next_step),
                (field(var("changes"), 0), lit(())))
    return let("checked", validate_body(),
               call("chain", lit(kernel.FnRef("read")), lit(kernel.FnRef("identity_doc")),
                    steps, var("checked")))


def merge_body():
    body = call("Merge.merge", var("source"), var("conflicts"))
    for path in reversed(hosts.PATHS):
        base = call("at", var("base"), lit(path))
        left = call("at", call("left_view", var("left")), lit(path))
        right = call("at", call("right_view", var("right")), lit(path))
        selected = case(call("eq", left, right), items(left, lit(False)),
                        case(call("eq", left, base), items(right, lit(False)),
                             case(call("eq", right, base), items(left, lit(False)),
                                  items(base, lit(True)))))
        next_conflicts = case(call("item_at", var("selection"), lit(1)),
                              call("append", var("conflicts"),
                                   card("Clash", lit(path), base, left, right)), var("conflicts"))
        body = let("selection", selected,
                   let("source", call("edit", var("source"), lit(path),
                                      call("item_at", var("selection"), lit(0))),
                       let("conflicts", next_conflicts, body)))
    return let("source", call("apply", var("base"), card("Patches", lit(()))),
               let("conflicts", lit(()), body))


def conflict_body():
    body = case(call("is_empty", var("pending")), var("result"),
                call("paths_loop", call("tail", var("pending")),
                     call("append", var("result"), field(call("head", var("pending")), 0))))
    return let("public", call("Merge.merge", doc(var("merge")), clashes(var("merge"))),
               rec("paths_loop", ("pending", "result"), body, (clashes(var("public")), lit(()))))


def resolve_body():
    choice = call("head", var("selected"))
    clash = call("head", var("pending"))
    side = call("item_at", choice, lit(1))
    value = case(call("eq", side, lit("base")), field(clash, 1),
                 case(call("eq", side, lit("left")), field(clash, 2),
                      case(call("eq", side, lit("right")), field(clash, 3),
                           call("reject", lit("domain")))))
    next_step = case(call("eq", field(clash, 0), call("item_at", choice, lit(0))),
                     call("resolve_loop", call("tail", var("pending")), call("tail", var("selected")),
                          call("edit", var("result"), field(clash, 0), value)),
                     call("reject", lit("domain")))
    body = case(call("is_empty", var("pending")),
                case(call("is_empty", var("selected")), var("result"), call("reject", lit("domain"))),
                case(call("is_empty", var("selected")), call("reject", lit("domain")), next_step))
    return let("paths", call("conflict_paths", var("merge")),
               case(call("eq", call("length", var("paths")), call("length", field(var("choices"), 0))),
                    rec("resolve_loop", ("pending", "selected", "result"), body,
                        (clashes(var("merge")), field(var("choices"), 0), doc(var("merge")))),
                    call("reject", lit("domain"))))


def commute_body():
    first = call("catch", call("apply", call("apply", var("base"), var("first")), var("second")))
    second = call("catch", call("apply", call("apply", var("base"), var("second")), var("first")))
    return let("forward", first, let("backward", second,
               case(call("eq", call("tag", var("forward")), lit("val")),
                    case(call("eq", call("tag", var("backward")), lit("val")),
                         call("eq", var("forward"), var("backward")), lit(False)), lit(False))))


def invert_body():
    body = case(call("is_empty", var("pending")), card("Patches", var("result")),
                let("change", call("head", var("pending")),
                    call("invert_loop", call("tail", var("pending")),
                         call("append", var("result"), patch(field(var("change"), 0),
                                                              field(var("change"), 2), field(var("change"), 1))))))
    return rec("invert_loop", ("pending", "result"), body, (field(var("changes"), 0), lit(())))


def rebase_body():
    old = var("source")
    next_doc = call("apply", old, call("head", var("pending")))
    prevalidated = rec("history_loop", ("pending", "source", "history"),
                       case(call("is_empty", var("pending")), var("history"),
                            let("next_doc", next_doc,
                                let("changes", call("delta", var("source"), var("next_doc")),
                                    case(call("eq", call("apply", var("next_doc"),
                                                         call("invert", var("changes"))), var("source")),
                                         call("history_loop", call("tail", var("pending")), var("next_doc"),
                                              call("append", var("history"),
                                                   items(var("source"), var("next_doc")))),
                                         call("reject", lit("guard")))))),
                       (var("steps"), var("base"), lit(())))
    pair = call("head", var("pending"))
    merged = call("three_way", lit(kernel.FnRef("read")), lit(kernel.FnRef("identity_doc")),
                  call("item_at", pair, lit(0)), call("current_view", var("current")),
                  call("item_at", pair, lit(1)))
    result = let("merged", merged,
                 case(call("is_empty", call("conflict_paths", var("merged"))),
                      call("replay_loop", call("tail", var("pending")),
                           call("current_view", doc(var("merged"))),
                           call("add", var("count"), lit(1))),
                      call("Replay.replay", doc(var("merged")), var("count"),
                           call("add", var("count"), lit(1)), clashes(var("merged")))))
    loop = rec("replay_loop", ("pending", "current", "count"),
               case(call("is_empty", var("pending")),
                    call("Replay.replay", var("current"), var("count"), lit(0), lit(())), result),
               (var("original"), call("onto_view", var("onto")), lit(0)))
    return let("original", prevalidated, loop)


SPECS = (
    ("patch", "object", ("path", "old", "new"), None, "Patch", "construct"),
    ("delta", "observation", ("before_doc", "after_doc"), delta_body(), "Patches", "read"),
    ("chain", "combinator", ("f", "g", "steps", "start"), chain_body(), "Doc", "compose"),
    ("apply", "operation", ("document", "changes"), apply_body(), "Doc", "act"),
    ("merge", "object", ("source", "conflicts"), None, "Merge", "construct"),
    ("three_way", "combinator", ("left_view", "right_view", "base", "left", "right"), merge_body(), "Merge", "combine"),
    ("conflict_paths", "observation", ("merge",), conflict_body(), "List", "read"),
    ("resolve", "operation", ("merge", "choices"), resolve_body(), "Doc", "act"),
    ("commute", "observation", ("base", "first", "second"), commute_body(), "bool", "read"),
    ("invert", "operation", ("changes",), invert_body(), "Patches", "transform"),
    ("replay", "object", ("document", "applied", "blocked", "conflicts"), None, "Replay", "construct"),
    ("rebase", "combinator", ("onto_view", "current_view", "base", "onto", "steps"), rebase_body(), "Replay", "interleave"),
)


def definitions():
    layers = {}
    result = []
    for name, kind, params, body, output, role in SPECS:
        slot_names = {"chain": {"f", "g"}, "three_way": {"left_view", "right_view"},
                      "rebase": {"onto_view", "current_view"}}
        refs = tuple(sorted(n.all_dependencies(body) - slot_names.get(name, set())
                            if body is not None else ()))
        layer = compute_layer(refs, lambda dependency: layers.get(dependency, 0))
        layers[name] = layer
        if kind == "object":
            spec = ObjectSpec(name.capitalize(), "compose", tags={name: [(param, "Value") for param in params]},
                              extra={"input_names": params})
        elif kind == "observation":
            spec = ObservationSpec(name, ("read",) if name == "delta" else (), body)
        elif kind == "combinator":
            spec = CombinatorSpec(name, params, tuple(param for param in params if param in slot_names.get(name, ())), body)
        else:
            spec = OperationSpec(name, role, tuple(Edge("Any", name=param) for param in params),
                                 Edge(output), name, errors=("domain", "guard"),
                                 extra={"input_names": list(params)})
        result.append(Definition(name, kind, "invented", layer, refs, spec, body))
    return tuple(result)


def entrypoint(name):
    return f"{name.capitalize()}.{name}" if name in ("patch", "merge", "replay") else name


def from_reference(value):
    ref = reference()
    if isinstance(value, ref.Doc):
        return hosts.doc(*(hosts.GONE if item is None else item for item in value.values))
    if isinstance(value, ref.Patch):
        return Card("Patch", "patch", (value.path, hosts.GONE if value.old is None else value.old,
                                         hosts.GONE if value.new is None else value.new))
    if isinstance(value, ref.Patches):
        return Card("Patches", "patches", (tuple(from_reference(item) for item in value.items),))
    if isinstance(value, ref.Clash):
        return Card("Clash", "clash", (value.path, *(hosts.GONE if item is None else item for item in
                                                    (value.base, value.left, value.right))))
    if isinstance(value, ref.Merge):
        return Card("Merge", "merge", (from_reference(value.doc), tuple(from_reference(item) for item in value.clashes)))
    if isinstance(value, ref.Replay):
        return Card("Replay", "replay", (from_reference(value.doc), value.applied, value.blocked,
                                           tuple(from_reference(item) for item in value.clashes)))
    if isinstance(value, ref.Choices):
        return Card("Choices", "choices", (value.values,))
    if isinstance(value, tuple):
        return tuple(from_reference(item) for item in value)
    return value


def to_reference(value, ref):
    if isinstance(value, Card):
        if value.sort == "Doc":
            return ref.Doc(tuple(None if item == hosts.GONE else item for item in value.fields))
        if value.sort == "Patch":
            return ref.Patch(value.fields[0], *(None if item == hosts.GONE else item for item in value.fields[1:]))
        if value.sort == "Patches":
            return ref.Patches(tuple(to_reference(item, ref) for item in value.fields[0]))
        if value.sort == "Clash":
            return ref.Clash(value.fields[0], *(None if item == hosts.GONE else item for item in value.fields[1:]))
        if value.sort == "Merge":
            return ref.Merge(to_reference(value.fields[0], ref), tuple(to_reference(item, ref) for item in value.fields[1]))
        if value.sort == "Choices":
            return ref.Choices(value.fields[0])
        if value.sort == "Replay":
            return ref.Replay(to_reference(value.fields[0], ref), value.fields[1], value.fields[2],
                              tuple(to_reference(item, ref) for item in value.fields[3]))
    if isinstance(value, tuple):
        return tuple(to_reference(item, ref) for item in value)
    return None if value == hosts.GONE else value


def samples():
    ref = reference()
    base = from_reference(ref.BASE)
    def patches(*triples):
        return from_reference(ref.patches(*(ref.Patch(*triple) for triple in triples)))
    left = patches(("/a", "0", "x"), ("/b", "0", "y"))
    right = patches(("/a", "0", "z"), ("/c", "0", "w"))
    merged = from_reference(ref.three_way(ref.fix(ref.apply, to_reference(left, ref)),
                                          ref.fix(ref.apply, to_reference(right, ref)), ref.BASE))
    return {
        "patch": (("/a", "0", "x"),),
        "delta": ((base, from_reference(ref.edit(ref.edit(ref.BASE, "/a", "x"), "/b", "y"))),),
        "chain": ((kernel.FnRef("read"), kernel.FnRef("identity_doc"),
                   (("/a", "x"), ("/b", "y")), base),),
        "apply": ((base, left),),
        "merge": ((base, (from_reference(ref.Clash("/a", "0", "x", "y")),)),),
        "three_way": ((kernel.FnRef("read"), kernel.FnRef("identity_doc"),
                        base, from_reference(ref.apply(ref.BASE, to_reference(left, ref))),
                        from_reference(ref.apply(ref.BASE, to_reference(right, ref)))),),
        "conflict_paths": ((merged,),),
        "resolve": ((merged, from_reference(ref.Choices((("/a", "right"),)))),),
        "commute": ((base, patches(("/a", "0", "x")), patches(("/b", "0", "y"))),),
        "invert": ((left,),),
        "replay": ((base, 0, 0, ()),),
        "rebase": ((kernel.FnRef("read"), kernel.FnRef("identity_doc"),
                    base, from_reference(ref.edit(ref.BASE, "/b", "y")),
                    (patches(("/a", "0", "x")), patches(("/c", "0", "z")))),),
    }


def reference_result(name, args):
    ref = reference()
    args = tuple(to_reference(arg, ref) for arg in args)
    if name in ("patch", "merge", "replay"):
        return from_reference({"patch": lambda: ref.Patch(*args),
                               "merge": lambda: ref.Merge(*args),
                               "replay": lambda: ref.Replay(*args)}[name]())
    if name == "chain":
        return from_reference(ref.chain(tuple(ref.fix(ref.edit, *step) for step in args[2]), args[3]))
    if name == "three_way":
        return from_reference(ref.three_way(lambda _: args[3], lambda _: args[4], args[2]))
    if name == "rebase":
        return from_reference(ref.rebase(lambda _: args[3], tuple(ref.fix(ref.apply, step) for step in args[4]), args[2]))
    if name == "apply":
        try:
            return from_reference(ref.apply(*args))
        except ref.GuardError:
            return Bottom("guard")
    return from_reference(getattr(ref, name)(*args))


def verification_cases(name, examples):
    ref = reference()
    base = hosts.base12()
    if name == "patch":
        return tuple(product(hosts.PATHS, ("0", "x", "y", hosts.GONE),
                             ("0", "x", "y", hosts.GONE)))
    cases = list(examples)
    for index, path in enumerate(hosts.PATHS):
        next_path = hosts.PATHS[(index + 1) % len(hosts.PATHS)]
        for value in ("x", "y", "z", hosts.GONE, "w"):
            other = "y" if value == "x" else "x"
            first = from_reference(ref.patches(ref.Patch(path, "0", None if value == hosts.GONE else value)))
            second = from_reference(ref.patches(ref.Patch(next_path, "0", "y")))
            changed = hosts.edit(base, path, value)
            next_doc = hosts.edit(base, next_path, "y")
            clash = from_reference(ref.Clash(path, "0", None if value == hosts.GONE else value, other))
            merged = Card("Merge", "merge", (base, (clash,)))
            choices = from_reference(ref.Choices(((path, "left" if index % 2 else "right"),)))
            options = {
                "delta": (base, changed),
                "chain": (kernel.FnRef("read" if index % 2 else "identity_doc"),
                          kernel.FnRef("identity_doc" if index % 2 else "read"),
                          ((path, value), (next_path, "y")), base),
                "apply": (base, first),
                "merge": (base, (clash,)),
                "three_way": (kernel.FnRef("read"), kernel.FnRef("identity_doc"),
                              base, changed, hosts.edit(base, path, other)),
                "conflict_paths": (merged,),
                "resolve": (merged, choices),
                "commute": (base, first, second),
                "invert": (first,),
                "replay": (changed, 0, 0, ()),
                "rebase": (kernel.FnRef("read"), kernel.FnRef("identity_doc"), base, next_doc, (first,)),
            }
            cases.append(options[name])
    return tuple(cases)


def invariant_laws():
    left_view = lit(kernel.FnRef("read"))
    right_view = lit(kernel.FnRef("identity_doc"))

    def untyped_doc(value):
        return field(call("Merge.merge", value, lit(())), 0)

    merge_left = call("three_way", left_view, right_view, var("base"), var("left"), var("right"))
    merge_right = call("three_way", left_view, right_view, var("base"), var("right"), var("left"))
    statements = (
        ("merge_idem", (("base", "Doc"), ("left", "Doc")),
         call("eq", doc(call("three_way", left_view, right_view, var("base"), var("left"), var("left"))),
              untyped_doc(var("left")))),
        ("merge_symmetric", (("base", "Doc"), ("left", "Doc"), ("right", "Doc")),
         call("eq", merge_left, merge_right)),
    )
    for name, variables, statement in statements:
        spec = LawSpec(name, variables, statement)
        dependencies = tuple(sorted(n.all_dependencies(statement)))
        yield Definition(name, "law", "invented", 1 + max(
            (next((item.layer for item in definitions() if item.name == dependency), 0)
             for dependency in dependencies), default=0), dependencies, spec, statement)


def law_cases(name):
    base = hosts.base12()
    docs = tuple(hosts.edit(base, path, value) for path in hosts.PATHS[:4] for value in ("x", "y"))
    if name == "merge_idem":
        return tuple((base, document) for document in (base, *docs))
    if name == "merge_symmetric":
        return tuple((base, left, right) for left in (base, *docs) for right in (base, *docs)
                     if not any(first != "0" and second != "0" and first != second
                                for first, second in zip(left.fields, right.fields)))
    raise ValueError(name)


def build_library():
    library = new_library()
    examples = samples()
    for definition in definitions():
        name = definition.name
        library.write(definition)
        library.check(name)
        library.make_callable(name, examples[name])
        domain = verification_cases(name, examples[name])
        method = "exhaustive" if name == "patch" else "bounded"
        scope = {"domain": ("all 12 paths x 4 old texts x 4 new texts" if name == "patch" else
                            "bound: 1 design witness plus 12 paths x 5 new values (x,y,z,Gone,w); "
                            "61 inputs, at most 2 edits per branch and 2 commits"),
                 "size": len(domain)}
        if name in ("chain", "three_way", "rebase"):
            family = ["read", "identity_doc"]
            scope["domain"] += "; 4 operation-slot assignments, 244 evaluations"
            scope["op_family"] = family
            slot_names = definition.spec.op_params
            request = VerifyRequest(method, tuple(args[2:] for args in domain), scope,
                                    reference=lambda assignment, inputs, name=name, slots=slot_names: reference_result(
                                        name, (kernel.FnRef(assignment[slots[0]]),
                                               kernel.FnRef(assignment[slots[1]]), *inputs)),
                                    extra={"op_family": family})
        else:
            request = VerifyRequest(method, domain, scope,
                                    reference=lambda *args, name=name: reference_result(name, args))
        library.verify(name, request)
        library.account(name)
        library.promote(name, Contract("Exact outcomes on the declared bounded witness domain; immutable inputs."))
    for definition in invariant_laws():
        name = definition.name
        domain = law_cases(name)
        library.write(definition)
        library.check(name)
        library.make_callable(name, domain[:1])
        library.verify(name, VerifyRequest("bounded", domain, {
            "domain": ("base12 and eight single edits on paths /a-/d with text x or y; "
                       "nine idempotent pairs" if name == "merge_idem" else
                       "73 non-conflicting ordered pairs from base12 and eight single edits "
                       "on paths /a-/d with text x or y"),
            "size": len(domain)}))
        library.account(name)
        library.promote(name, Contract("Holds on the stated finite version-document witnesses."))
    return library
