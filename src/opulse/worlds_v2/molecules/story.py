"""Twelve invented molecular definitions, with measured kernel unfolding."""

from itertools import combinations, product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Card, boolean

from . import hosts
from .world import new_library


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def rec(fn, params, body, args, measure):
    return n.Rec(fn, params, body, args, measure=measure)


def when(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def operation(name, params, body, layer=1, output="List"):
    spec = OperationSpec(name, "transform", tuple(Edge("int" if param in {"size", "carbon", "oxygen", "edges"}
                                                      else "unknown", name=param) for param in params),
                         Edge(output), f"Kernel-defined {name}.", extra={"input_names": list(params)})
    return Definition(name, "operation", "invented", layer,
                      tuple(sorted(n.references(body))), spec, body)


def observation(name, params, body, reads, layer):
    spec = ObservationSpec(name, tuple(reads), body, extra={"subject": params[0]})
    return Definition(name, "observation", "invented", layer,
                      tuple(sorted(n.references(body))), spec, body)


def combinator(name, params, slots, body, layer):
    spec = CombinatorSpec(name, tuple(params), tuple(slots), body)
    return Definition(name, "combinator", "invented", layer,
                      tuple(sorted(n.references(body) - set(slots))), spec, body)


def definitions():
    graph = var("g")
    edges = var("edges")
    remaining = var("remaining")
    index = call("minus", remaining, lit(1))
    edge = var("edge")
    left = call("pair_left", edge)
    right = call("pair_right", edge)
    seen = var("seen")
    add_right = when(call("list_contains", seen, left), call("list_add_unique", seen, right), seen)
    add_left = when(call("list_contains", var("next"), right),
                    call("list_add_unique", var("next"), left), var("next"))
    sweep = rec("sweep", ("remaining", "seen"),
                when(call("equal", remaining, lit(0)), seen,
                     n.Let("edge", call("list_get", edges, index),
                           n.Let("next", add_right, call("sweep", index, add_left)))),
                (call("count", edges), var("seen")), remaining)
    reach = rec("reach", ("remaining", "seen"),
                when(call("equal", remaining, lit(0)),
                     call("equal", call("count", seen), call("count", call("graph_labels", graph))),
                     call("reach", call("minus", remaining, lit(1)), sweep)),
                (call("count", call("graph_labels", graph)), lit(hosts.list_make(0))), remaining)
    connected = operation("connected", ("g",), n.Let("edges", call("graph_edges", graph), reach), output="bool")

    relabel_body = call("graph_create", call("list_permute", call("graph_labels", graph), var("order")),
                        call("list_reindex_pairs", call("graph_edges", graph), var("order")),
                        call("list_permute", call("graph_hydrogen", graph), var("order")))
    relabel = operation("relabel", ("g", "order"), relabel_body, output="Graph")
    start = var("start")
    end = var("end")
    width = call("minus", end, start)
    choose = rec("choose", ("start", "end"),
                 when(call("equal", width, lit(1)),
                      call("relabel", graph, call("list_get", var("perms"), start)),
                      n.Let("middle", call("plus", start, call("small_half", width)),
                            n.Let("first_best", call("choose", start, var("middle")),
                                  n.Let("second_best", call("choose", var("middle"), end),
                                        when(call("less", call("graph_key", var("first_best")),
                                                  call("graph_key", var("second_best"))),
                                             var("first_best"), var("second_best")))))),
                 (lit(0), call("count", var("perms"))), width)
    normalize_body = n.Let("perms", call("list_label_permutations", call("graph_labels", graph),
                                        call("graph_hydrogen", graph)), choose)
    normalize = operation("normalize", ("g",), normalize_body, layer=2, output="Graph")

    molecule = Definition("Molecule", "object", "invented", 3, ("graph_valid", "connected", "normalize"),
                          ObjectSpec("Molecule", "refine", base="Graph",
                                     valid=n.Case(((n.Test(call("graph_valid", var("x"))),
                                                    call("connected", var("x"))),),
                                                  lit(boolean(False))),
                                     canon=call("normalize", var("x"))), None)

    vertex = var("vertex")
    triple = call("list_get", call("view_vertices", var("view")), vertex)
    free = call("triple_get", triple, lit(2))
    fill = rec("fill", ("remaining", "g"),
               when(call("equal", remaining, lit(0)), var("g"),
                    call("fill", call("minus", remaining, lit(1)),
                         call("attach", var("g"), lit("H"), vertex))),
               (free, graph), remaining)
    saturate_body = n.Let("view", call("atoms", graph),
                          rec("saturate_vertices", ("remaining", "g"),
                              when(call("equal", remaining, lit(0)), call("Molecule.make", var("g")),
                                   n.Let("vertex", call("minus", remaining, lit(1)),
                                         call("saturate_vertices", var("vertex"), fill))),
                              (call("count", call("view_vertices", var("view"))), graph), remaining))
    saturate = operation("saturate", ("g",), saturate_body, layer=4, output="Molecule")

    finish_body = call("saturate", call("f", graph))
    finish = combinator("finish", ("f", "g"), ("f",), finish_body, 5)

    mol = var("m")
    view = call("atoms", call("Molecule.base", mol))
    vertices = call("view_vertices", var("view"))
    row = call("list_get", vertices, index)
    label = call("triple_get", row, lit(0))
    hydrogens = call("triple_get", row, lit(1))
    count_formula = rec("formula_parts", ("remaining", "carbon", "hydrogen", "oxygen"),
                        when(call("equal", remaining, lit(0)),
                             call("text_concat", call("text_concat", call("text_concat", call("text_concat",
                                  lit("C"), call("text_of_int", var("carbon"))), lit("H")),
                                  call("text_of_int", var("hydrogen"))),
                                  call("text_concat", lit("O"), call("text_of_int", var("oxygen")))),
                             n.Let("row", row,
                                   call("formula_parts", index,
                                        call("plus", var("carbon"), when(call("equal", label, lit("C")), lit(1), lit(0))),
                                        call("plus", var("hydrogen"), hydrogens),
                                        call("plus", var("oxygen"), when(call("equal", label, lit("O")), lit(1), lit(0)))))),
                        (call("count", vertices), lit(0), lit(0), lit(0)), remaining)
    formula = observation("formula", ("m",), n.Let("view", view,
                           n.Let("vertices", call("view_vertices", var("view")), count_formula)), ("atoms", "count"), 4)

    cycles_body = n.Let("view", view, call("plus", call("minus", call("count", call("view_edges", var("view"))),
                                                          call("count", call("view_vertices", var("view")))), lit(1)))
    cycle_rank = observation("cycle_rank", ("m",), cycles_body, ("atoms", "count"), 4)

    pairs = rec("make_pairs", ("remaining", "pairs"),
                when(call("equal", remaining, lit(0)), var("pairs"),
                     n.Let("left", call("minus", remaining, lit(1)),
                           call("make_pairs", var("left"),
                                rec("make_right", ("right", "pairs"),
                                    when(call("equal", var("right"), var("size")), var("pairs"),
                                         call("make_right", call("plus", var("right"), lit(1)),
                                              call("list_append", var("pairs"), call("pair_make", var("left"), var("right"))))),
                                    (call("plus", var("left"), lit(1)), var("pairs")),
                                    call("minus", var("size"), var("right")))))),
                (var("size"), call("list_make")), remaining)
    all_pairs = operation("all_pairs", ("size",),
                          when(call("less", var("size"), lit(0)), call("always_fail", lit("size")),
                               when(call("less", lit(8), var("size")), call("always_fail", lit("size")),
                                    call("list_sort", pairs))), output="List")

    carbon = var("carbon")
    oxygen = var("oxygen")
    edge_count = var("edges")
    size = call("plus", carbon, oxygen)
    labels_full = n.Let("first", call("list_repeat", lit("C"), carbon),
                        rec("append_oxygen", ("remaining", "labels"),
                            when(call("equal", remaining, lit(0)), var("labels"),
                                 call("append_oxygen", call("minus", remaining, lit(1)),
                                      call("list_append", var("labels"), lit("O")))),
                            (oxygen, var("first")), remaining))
    selected = call("list_get", var("subsets"), index)
    raw = call("graph_raw", var("labels"), selected, call("list_repeat", lit(0), var("size")))
    molecule_from_raw = call("finish", lit(kernel.FnRef("identity")), var("raw"))
    insert = call("list_insert_pair", var("acc"),
                  call("pair_make", call("graph_key", call("Molecule.base", var("item"))), var("item")))
    candidate_loop = rec("enumerate", ("remaining", "acc"),
                         when(call("equal", remaining, lit(0)), call("list_rights", var("acc")),
                              n.Let("raw", raw,
                                    when(call("graph_valid", var("raw")),
                                         when(call("connected", var("raw")),
                                              n.Let("item", molecule_from_raw,
                                                    call("enumerate", index, insert)),
                                              call("enumerate", index, var("acc"))),
                                         call("enumerate", index, var("acc"))))),
                         (call("count", var("subsets")), call("list_make")), remaining)
    candidates_body = when(call("less", carbon, lit(0)), call("always_fail", lit("enumeration_bound")),
                      when(call("less", oxygen, lit(0)), call("always_fail", lit("enumeration_bound")),
                      when(call("less", size, lit(2)), call("always_fail", lit("enumeration_bound")),
                      when(call("less", lit(6), size), call("always_fail", lit("enumeration_bound")),
                      when(call("less", edge_count, call("minus", size, lit(1))),
                           call("always_fail", lit("enumeration_bound")),
                      when(call("less", size, edge_count), call("always_fail", lit("enumeration_bound")),
                           n.Let("size", size, n.Let("labels", labels_full,
                                n.Let("pairs", call("all_pairs", var("size")),
                                      when(call("less", call("count", var("pairs")), edge_count), call("list_make"),
                                           n.Let("subsets", call("list_combinations", var("pairs"), edge_count),
                                                 candidate_loop)))))))))))
    candidates = operation("candidates", ("carbon", "oxygen", "edges"), candidates_body, layer=6, output="List")

    eleft, eright = call("pair_left", var("edge")), call("pair_right", var("edge"))
    other = when(call("equal", eleft, vertex), eright, eleft)
    adjacent = when(call("equal", eleft, vertex), lit(boolean(True)), call("equal", eright, vertex))
    has_carbon = rec("neighbor", ("remaining",),
                     when(call("equal", remaining, lit(0)), lit(boolean(False)),
                          n.Let("edge", call("list_get", var("edges"), index),
                                when(adjacent, when(call("equal", call("triple_get",
                                    call("list_get", vertices, other), lit(0)), lit("C")),
                                    lit(boolean(True)), call("neighbor", index)), call("neighbor", index)))),
                     (call("count", var("edges")),), remaining)
    oh_scan = rec("oh_scan", ("remaining", "total"),
                  when(call("equal", remaining, lit(0)), var("total"),
                       n.Let("vertex", index,
                             call("oh_scan", index, call("plus", var("total"),
                                  when(call("equal", call("triple_get", call("list_get", vertices, vertex), lit(0)), lit("O")),
                                       when(call("less", lit(0), call("triple_get", call("list_get", vertices, vertex), lit(1))),
                                            when(has_carbon, lit(1), lit(0)), lit(0)), lit(0)))))),
                  (call("count", vertices), lit(0)), remaining)
    oh_count = observation("oh_count", ("m",), n.Let("view", view,
                           n.Let("vertices", call("view_vertices", var("view")),
                                 n.Let("edges", call("view_edges", var("view")), oh_scan))), ("atoms", "count"), 4)

    item = call("list_get", var("xs"), index)
    screened = rec("screen_loop", ("remaining", "out"),
                   when(call("equal", remaining, lit(0)), var("out"),
                        call("screen_loop", index, when(call("equal", call("probe", item), var("target")),
                             call("list_prepend", var("out"), item), var("out")))),
                   (call("count", var("xs")), call("list_make")), remaining)
    screen = combinator("screen", ("probe", "target", "xs"), ("probe",), screened, 1)

    profile_spec = ObjectSpec("Profile", "compose", tags={"profile": [
        ["formula", "str"], ["cycles", "int"], ["oh", "int"], ["carbon_branches", "int"]]})
    profile_object = Definition("Profile", "object", "invented", 1, (), profile_spec, None)

    degree = rec("degree", ("remaining", "total"),
                 when(call("equal", remaining, lit(0)), var("total"),
                      n.Let("edge", call("list_get", var("edges"), index),
                            call("degree", index, call("plus", var("total"), when(adjacent, lit(1), lit(0)))))),
                 (call("count", var("edges")), lit(0)), remaining)
    branch_scan = rec("branches", ("remaining", "total"),
                      when(call("equal", remaining, lit(0)), var("total"),
                           n.Let("vertex", index,
                                 call("branches", index, call("plus", var("total"),
                                      when(call("equal", call("triple_get", call("list_get", vertices, vertex), lit(0)), lit("C")),
                                           when(call("less", lit(2), degree), lit(1), lit(0)), lit(0)))))),
                      (call("count", vertices), lit(0)), remaining)
    branches_body = n.Let("view", view, n.Let("vertices", call("view_vertices", var("view")),
                     n.Let("edges", call("view_edges", var("view")), branch_scan)))
    carbon_branches = operation("carbon_branches", ("m",), branches_body, layer=4, output="int")
    profile_body = call("Profile.profile", call("formula", mol), call("cycle_rank", mol),
                        call("oh_count", mol), call("carbon_branches", mol))
    profile = operation("profile", ("m",), profile_body, layer=5, output="Profile")

    lookup = call("probe", item)
    partition_body = rec("partition_loop", ("remaining", "groups"),
                         when(call("equal", remaining, lit(0)), call("list_sort_groups", var("groups")),
                              n.Let("item", item, call("partition_loop", index,
                                   call("list_groups_insert", var("groups"), lookup,
                                        call("graph_key", call("Molecule.base", var("item"))))))),
                         (call("count", var("xs")), call("list_make")), remaining)
    partition = combinator("partition", ("probe", "xs"), ("probe",), partition_body, 4)

    group = call("list_get", var("groups"), index)
    group_key = call("pair_left", var("group"))
    group_members = call("pair_right", var("group"))
    current_count = call("count", group_members)
    winner_count = call("count", call("pair_right", var("winner")))
    checked_key = call("Profile.profile", call("Profile.formula", group_key),
                       call("Profile.cycles", group_key), call("Profile.oh", group_key),
                       call("Profile.carbon_branches", group_key))
    better_group = when(call("less", winner_count, current_count), var("group"),
                        when(call("equal", winner_count, current_count),
                             when(call("value_less", group_key, call("pair_left", var("winner"))),
                                  var("group"), var("winner")), var("winner")))
    find_max = rec("max_group", ("remaining", "winner"),
                   when(call("equal", remaining, lit(0)), var("winner"),
                        n.Let("group", group,
                              n.Let("verified", checked_key,
                                    when(call("equal", var("verified"), group_key),
                                         call("max_group", index, better_group),
                                         call("always_fail", lit("invalid")))))),
                   (call("count", var("groups")), call("list_get", var("groups"), lit(0))), remaining)
    ambiguity_body = when(call("equal", call("count", var("groups")), lit(0)),
                          call("always_fail", lit("empty")),
                          n.Let("sizes", call("group_sizes", var("groups")),
                                n.Let("winner", find_max,
                                      call("record_make", call("pair_left", var("winner")),
                                           call("count", call("pair_right", var("winner"))),
                                           call("list_take", call("pair_right", var("winner")), lit(2))))))
    ambiguity = observation("ambiguity", ("groups",), ambiguity_body, ("group_sizes", "count"), 2)

    return (connected, relabel, normalize, molecule, saturate, finish, formula, cycle_rank,
            all_pairs, candidates, oh_count, screen, profile_object, carbon_branches,
            profile, partition, ambiguity)


TOWER = ("Molecule", "saturate", "finish", "formula", "cycle_rank", "candidates",
         "oh_count", "screen", "Profile", "profile", "partition", "ambiguity")


def verification_graphs():
    graphs = set()
    for size in range(1, 4):
        for labels in product("CO", repeat=size):
            pairs = tuple(combinations(range(size), 2))
            for mask in range(1 << len(pairs)):
                edges = tuple(edge for index, edge in enumerate(pairs) if mask & 1 << index)
                for hydrogen in product(range(2), repeat=size):
                    graph = hosts.to_card(labels, edges, hydrogen)
                    if hosts.graph_valid(graph) == boolean(True):
                        graphs.add(graph)
    return tuple(sorted(graphs, key=lambda graph: (len(graph.fields[0].fields), hosts.graph_key(graph))))


def build_library(first_three=False):
    lib = new_library()
    graphs = verification_graphs()
    carbon = hosts.to_card(("C",))
    molecule = Card("Molecule", "val", (carbon,))
    mols = ()
    for definition in definitions():
        name = definition.name
        lib.write(definition)
        lib.check(name)
        if name in ("Molecule", "Profile"):
            sample = ((carbon,),) if name == "Molecule" else (("C1H4O0", 0, 0, 0),)
        elif name in ("connected", "normalize", "saturate"):
            sample = ((carbon,),)
        elif name == "relabel":
            sample = ((carbon, hosts.list_make(0)),)
        elif name == "finish":
            sample = ((kernel.FnRef("identity"), carbon),)
        elif name in ("formula", "cycle_rank", "oh_count", "carbon_branches", "profile"):
            sample = ((molecule,),)
        elif name == "all_pairs":
            sample = ((3,),)
        elif name == "candidates":
            sample = ((2, 0, 1),)
        elif name == "screen":
            sample = ((kernel.FnRef("oh_count"), 0, hosts.list_make(molecule)),)
        elif name == "partition":
            sample = ((kernel.FnRef("profile"), hosts.list_make(molecule)),)
        else:
            sample = ((hosts.list_make(hosts.pair_make(Card("Profile", "profile", ("C1H4O0", 0, 0, 0)),
                                                     hosts.list_make(hosts.graph_key(hosts.to_card(("C",), hydrogen=(4,)))))),),)
        lib.make_callable(name, sample)
        if name in ("Molecule", "normalize", "connected", "saturate", "relabel"):
            source = graphs[:65] if name != "saturate" else (
                graph for graph in graphs if lib.run("connected", (graph,)).outcome.value == boolean(True))
            domain = tuple((graph, hosts.list_make(*reversed(range(len(graph.fields[0].fields)))))
                           if name == "relabel" else (graph,) for graph in source)[:65]
        elif name == "Profile":
            profiles = tuple(Card("Profile", "profile", (f"C{index}H{index*2}O0",
                                                          index % 2, index % 3, index % 4))
                             for index in range(50))
            domain = (("C0H0O0", 0, profiles[0]),) + tuple(
                (item, item, item) for item in profiles[1:])
        elif name == "all_pairs":
            domain = tuple((index,) for index in range(9))
        elif name == "candidates":
            bounded = {(carbon_count, size - carbon_count, edge_count)
                       for size in range(2, 5) for carbon_count in range(size + 1)
                       for edge_count in (size - 1, size)}
            invalid = {(carbon_count, 3 - carbon_count, edge_count)
                       for carbon_count in range(4) for edge_count in range(7)}
            invalid.update((carbon_count, 4 - carbon_count, edge_count)
                           for carbon_count in range(5) for edge_count in (0, 7))
            domain = tuple(sorted(bounded | invalid))
        elif name in ("formula", "cycle_rank", "oh_count", "carbon_branches", "profile"):
            domain = tuple((item,) for item in mols[:55])
        elif name == "finish":
            domain = tuple((graph,) for graph in graphs[:55])
        elif name == "screen":
            domain = tuple((target, hosts.list_make(*mols[:index])) for target in range(3)
                           for index in range(1, 19))
        elif name == "partition":
            domain = tuple((hosts.list_make(*mols[offset:offset + size]),)
                           for size in range(1, 6) for offset in range(10))
        else:
            unique_molecules = tuple(dict.fromkeys(mols))[:50]
            domain = tuple((hosts.list_make(hosts.pair_make(
                lib.run("profile", (item,)).outcome.value,
                hosts.list_make(hosts.graph_key(item.fields[0])))),)
                for item in unique_molecules)
        family = {"finish": ["identity", "normalize"], "screen": ["oh_count", "cycle_rank"],
                  "partition": ["profile", "formula"]}.get(name)
        from .reference import combine as reference_combine
        from .reference import observe as reference_observe
        from .reference import operation as reference_operation
        reference = (reference_operation(name) if definition.kind == "operation" else
                     reference_observe(name) if definition.kind == "observation" else
                     reference_combine(name) if definition.kind == "combinator" else None)
        scopes = {
            "Molecule": "first 65 valid C/O graphs ordered by heavy count and code, <=3 heavy vertices, H per vertex 0..1",
            "normalize": "first 65 valid C/O graphs ordered by heavy count and code, <=3 heavy vertices, H per vertex 0..1",
            "relabel": "first 65 valid C/O graphs with <=3 heavy vertices and reversed vertex permutations",
            "connected": "first 65 valid C/O graphs ordered by heavy count and code, <=3 heavy vertices, H per vertex 0..1",
            "saturate": "first 65 connected valid C/O graphs ordered by heavy count and code, <=3 heavy vertices, H per vertex 0..1",
            "finish": "first 55 valid C/O graphs ordered by heavy count and code, <=3 heavy vertices, H per vertex 0..1, two graph transformations",
            "all_pairs": "complete supported size domain 0..8, nine integers",
            "candidates": "all C/O compositions of 2..4 heavy atoms at edge budgets n-1 and n, plus explicitly enumerated invalid budgets 0..7",
            "Profile": "50 distinct four-field Profiles with formula CkH2kO0, k=0..49; constructor inputs are C0H0O0 and 0",
            "formula": "first 55 connected <=3-heavy C/O molecular graphs with H per vertex 0..1",
            "cycle_rank": "first 55 connected <=3-heavy C/O molecular graphs with H per vertex 0..1",
            "oh_count": "first 55 connected <=3-heavy C/O molecular graphs with H per vertex 0..1",
            "carbon_branches": "first 55 connected <=3-heavy C/O molecular graphs with H per vertex 0..1",
            "profile": "first 55 connected <=3-heavy C/O molecular graphs with H per vertex 0..1",
            "screen": "three target values 0..2 on prefixes of lengths 1..18, two observation probes",
            "partition": "prefixes of sizes 1..5 at ten offsets of connected <=3-heavy C/O molecules, two probes",
            "ambiguity": "50 single-group inputs, each with its actual molecular Profile and valid canonical C/O graph code",
        }
        request = VerifyRequest("exhaustive" if name == "all_pairs" else "bounded", domain,
                                {"domain": scopes[name],
                                                   "size": len(domain), **({"op_family": family} if family else {}),
                                                   **({"fixed_ops": []} if definition.kind == "combinator" else {})},
                                reference=reference, extra={"op_family": family} if family else {})
        lib.verify(name, request)
        lib.account(name)
        lib.promote(name, Contract(f"{name} unfolds to its public finite graph and list rules"))
        if name == "Molecule":
            mols = tuple(lib.run("Molecule.make", (graph,)).outcome.value for graph in graphs
                         if lib.run("connected", (graph,)).outcome.value == boolean(True))
        if first_three and name == "finish":
            return lib
    return lib
