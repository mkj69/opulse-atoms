"""Nine story operations and one helper, checked and promoted through the core library."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Contract, Definition, Edge, OperationSpec
from opulse.atoms.values import Card, boolean

from . import hosts, reference
from .world import new_library


def var(name):
    return n.Var(name)


def call(name, *args):
    return n.Call(name, args)


def definitions():
    edge, forward, backward = var("e"), var("forward"), var("backward")
    source = call("source", edge)
    target = call("target", edge)
    length = call("add", call("add", call("depth_at", forward, source), n.Lit(1)),
                  call("depth_at", backward, target))
    count = call("mul", call("ways_at", forward, source), call("ways_at", backward, target))
    predicate = n.Case(((n.And(n.Test(call("eq", length, call("maxdepth", forward))),
                              n.Test(call("eq", count, call("longest_count", forward)))),
                         n.Lit(boolean(True))),), n.Lit(boolean(False)))
    expressions = (
        ("step", ("r",), call("subtract", var("r"), call("id", var("r")))),
        ("expand", ("x", "r"), call("union", var("x"),
                                     call("compose", var("x"), call("step", var("r"))))),
        ("reach", ("r",), call("fix2", n.Lit(kernel.FnRef("expand")),
                                 call("id", var("r")), var("r"))),
        ("mutual", ("r",), call("intersect", call("reach", var("r")),
                                     call("transpose", call("reach", var("r"))))),
        ("condense", ("r",), call("quotient", call("step", var("r")),
                                       call("mutual", var("r")))),
        ("advance", ("p", "u", "v"),
         n.Let("candidate", call("add", call("depth_at", var("p"), var("u")), n.Lit(1)),
               n.Case(((n.Test(call("lt", call("depth_at", var("p"), var("v")),
                                      var("candidate"))),
                        call("set_profile", var("p"), var("v"), var("candidate"),
                             call("ways_at", var("p"), var("u")))),
                       (n.Test(call("eq", var("candidate"),
                                       call("depth_at", var("p"), var("v")))),
                        call("set_profile", var("p"), var("v"),
                             call("depth_at", var("p"), var("v")),
                             call("add", call("ways_at", var("p"), var("v")),
                                  call("ways_at", var("p"), var("u")))))), var("p")))),
        ("profile", ("d",), call("dag_fold", n.Lit(kernel.FnRef("advance")), var("d"))),
        ("critical_edge", ("e", "forward", "backward"), predicate),
        ("critical", ("d",), n.Let("forward", call("profile", var("d")),
                          n.Let("backward", call("profile", call("transpose", var("d"))),
                                call("each", n.Lit(kernel.FnRef("critical_edge")), var("d"),
                                     var("forward"), var("backward"))))),
        ("backbone", ("r",), call("critical", call("condense", var("r")))),
    )
    layers = {}
    for name, parameters, body in expressions:
        dependencies = tuple(sorted(all_dependencies(Definition(name, "operation", "invented", 1,
                          (), OperationSpec(name, "transform", (), Edge("unknown"), name), body))))
        layer = 1 + max((layers.get(item, 0) for item in dependencies), default=0)
        layers[name] = layer
        inputs = tuple(Edge("Profile" if param in ("p", "forward", "backward")
                             else "Edge" if param == "e" else "int" if param in ("u", "v") else "Rel",
                             name=param) for param in parameters)
        output = "bool" if name == "critical_edge" else "Profile" if name in ("advance", "profile") else "Rel"
        spec = OperationSpec(name, "transform", inputs, Edge(output),
                             f"Derive {name} from fixed public operators and previous operations.",
                             extra={"input_names": list(parameters)})
        yield Definition(name, "operation", "invented", layer, dependencies, spec, body)


def sample(name):
    graph = hosts.pack(reference.braid(4, 2, 3, (1,)))
    dag = hosts.pack(reference.condense(reference.braid(4, 2, 3, (1,))))
    if name == "expand":
        return (hosts.identity(graph), graph)
    if name == "advance":
        return (Card("Profile", "Profile", (Card("List", "items", (0, 0)),
                                            Card("List", "items", (1, 1)))), 0, 1)
    if name == "critical_edge":
        graph = hosts.relation(dag)
        edge = next(graph.edges())
        forward = hosts.pack_profile(reference.profile(reference.Rel(graph.size, graph.rows)))
        reversed_graph = reference.transpose(reference.Rel(graph.size, graph.rows))
        backward = hosts.pack_profile(reference.profile(reversed_graph))
        return (Card("Edge", "Edge", edge), forward, backward)
    return (dag,) if name in ("profile", "critical") else (graph,)


def expected(name, *args):
    def original(value):
        graph = hosts.relation(value)
        return reference.Rel(graph.size, graph.rows)

    if name == "advance":
        profile = hosts.profile_value(args[0])
        original_profile = reference.Profile(profile.depth, profile.ways)
        reference.advance(original_profile, *args[1:])
        return hosts.pack_profile(original_profile)
    if name == "profile":
        return hosts.pack_profile(reference.profile(original(args[0])))
    if name == "expand":
        return hosts.pack(reference.expand(*(original(arg) for arg in args)))
    if name == "critical_edge":
        edge, forward, backward = args
        source, target = edge.fields
        front = hosts.profile_value(forward)
        back = hosts.profile_value(backward)
        return boolean(front.depth[source] + 1 + back.depth[target] == max(front.depth)
                       and front.ways[source] * back.ways[target] == reference.longest_count(
                           reference.Profile(front.depth, front.ways)))
    return hosts.pack(getattr(reference, name)(original(args[0])))


def build_library():
    library = new_library()
    for definition in definitions():
        library.write(definition)
        library.check(definition.name)
        domain = (sample(definition.name),)
        library.make_callable(definition.name, domain)
        library.verify(definition.name, VerifyRequest("bounded", domain,
                       {"domain": "one explicit finite braid or profile input", "size": len(domain)},
                       reference=lambda *args, name=definition.name: expected(name, *args)))
        library.account(definition.name)
        library.promote(definition.name, Contract(f"{definition.name}: exact over the bounded checked domain"))
    return library
