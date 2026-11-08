"""The generator adapters reflect the active deep catalogue declarations."""

from dataclasses import replace
from itertools import islice, product
from pathlib import Path

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.kernel import FnRef, call
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom, Ok, truth
from opulse.gen_v2 import configs
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.fast import deep
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.worlds import (
    action,
    automata,
    calendar,
    circuits,
    classic,
    comb_obs,
    comb_only,
    dice,
    geometry,
    grammar,
    hidden,
    integer,
    kitchen,
    lists,
    melody,
    molecules,
    obj_only,
    obj_op,
    obs_only,
    op_only,
    permutation,
    pixels,
    rhythm,
    roads,
    shadows,
    text,
    versions,
)
from opulse.gen_v2.worlds._common import generator_decl, world_tags
from opulse.worlds_v2.action import hosts as action_hosts
from opulse.worlds_v2.automata import hosts as automata_hosts
from opulse.worlds_v2.circuits import hosts as circuit_hosts
from opulse.worlds_v2.permutation import hosts as permutation_hosts

CATALOGUE = (lists, circuits, action, versions, integer, dice, rhythm,
             hidden, grammar, automata, calendar, geometry, kitchen, melody,
             molecules, permutation, pixels, roads, shadows, text,
             op_only, obs_only, obj_only, comb_only, comb_obs, obj_op)
if configs.world_installed("opulse.worlds_v2.computer2.world"):  # tasks-owned world
    from opulse.gen_v2.worlds import computer

    CATALOGUE += (computer,)
CLASSIC = ("successor", "integer", "clock", "bits", "strings", "lists",
           "logic", "perm", "rel", "grid", "pitch", "action")
ADAPTERS = [pytest.param(classic.gen_world, name, id=f"legacy-{name}") for name in CLASSIC]
ADAPTERS += [pytest.param(module.gen_world, None,
                          id=f"v2-{module.__name__.rsplit('.', 1)[-1]}")
             for module in CATALOGUE if module not in
             (op_only, obs_only, obj_only, comb_only, comb_obs, obj_op)]


def state(world):
    return GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                     world.extra_scope, world.signatures), dict(world.sorts))


def candidate(name, inputs, output, body):
    spec = OperationSpec(name, "transform", tuple(Edge(sort) for sort in inputs),
                         Edge(output), "Generated test composition.")
    definition = Definition(name, "operation", "invented", 1,
                            tuple(sorted(n.references(body))), spec, body)
    return Candidate(definition, Signature(inputs, output), "test.world")


@pytest.mark.parametrize(("factory", "name"), ADAPTERS)
def test_world_tags_match_declaration(factory, name):
    world = factory(name) if name else factory()
    module = __import__(factory.__module__, fromlist=["TAGS"])
    tags = module.TAGS[name] if name else module.TAGS
    assert world.tags == tags
    assert world.title
    assert set(tags) == {"domain", "modalities", "open_kinds", "star_kind", "reasoning",
                         "state", "outcomes", "visibility", "agents", "scale", "difficulty", "uses"}
    assert tags["open_kinds"] == sorted(world.open_kinds)
    assert tags["star_kind"] in world.open_kinds


@pytest.mark.parametrize(("factory", "name"), ADAPTERS)
def test_world_has_usable_typed_scope(factory, name):
    world = factory(name) if name else factory()
    scope = state(world).library.scope()
    for atom, signature in world.signatures.items():
        assert scope.resolve(atom) is not None, (world.name, atom)
        for sort in (*signature.inputs, signature.output):
            assert len(world.sorts[sort].values) >= 2, (world.name, sort)
    if world.truth_sort:
        assert len(world.truth_states) >= 20
        assert world.probes
        assert all(scope.resolve(probe).kind == "observation" for probe in world.probes)
    if name:
        assert world.open_kinds == frozenset({"operation"})
        assert world.dialect == "legacy-v1"
    else:
        assert world.dialect == "atoms-v2"
        assert {"object", "operation", "combinator", "observation"} <= world.open_kinds


@pytest.mark.parametrize(("factory", "name"), ADAPTERS)
def test_world_admits_two_call_composition(factory, name):
    world = factory(name) if name else factory()
    value = n.Var("arg0")
    if name == "successor":
        operation, sort = "natural_succ", "int"
        body = n.Call(operation, (n.Call(operation, (value,)),))
    elif name == "bits":
        sort = "int"
        body = n.Call("bit_count", (n.Call("bit_xor", (value, n.Lit(5))),))
    elif name == "action":
        sort = "state"
        body = n.Call("front_height", (n.Call("turn_right", (value,)),))
    elif world.name == "computer":
        sort = "int"
        body = n.Call("inc", (n.Call("inc", (value,)),))
    else:
        operation = next((item for item in ("add", "integer_add", "int_add", "plus", "decrease")
                          if item in world.signatures and
                          world.signatures[item] == Signature(("int", "int"), "int")), None)
        assert operation is not None, world.name
        sort = "int"
        body = n.Call(operation, (n.Call(operation, (value, value)), value))
    output = "int" if name in ("action", "bits") else sort
    result = deep(admit, state(world), candidate("f900", (sort,), output, body))
    assert isinstance(result, Entry), (world.name, result)
    assert result.steps_max >= 1


@pytest.mark.parametrize(("factory", "name"), ADAPTERS)
def test_decisions_vary_across_probe_domain(factory, name):
    world = factory(name) if name else factory()
    atoms = {atom.name: atom for atom in world.atoms}
    varying = set()
    for atom_name, signature in world.signatures.items():
        if signature.output != "bool" or atom_name not in atoms or not signature.inputs:
            continue
        domains = [world.sorts[sort].values for sort in signature.inputs]
        seen = set()
        for args in islice(product(*domains), 2048):
            try:
                outcome = atoms[atom_name].fn(*args)
            except (TypeError, ValueError, IndexError, AttributeError, KeyError, ZeroDivisionError):
                continue
            if not isinstance(outcome, Bottom):
                seen.add(truth(outcome))
            if seen == {False, True}:
                break
        if seen == {False, True}:
            varying.add(atom_name)
        if name:
            assert seen == {False, True}, (world.name, atom_name, seen)
    assert varying or not any(sig.output == "bool" for sig in world.signatures.values()), world.name
    if not name:
        expected = {
            "lists": "is_empty", "circuits": "integer_lt", "action": "front_wall",
            "versions": "eq", "integer": "is_empty", "dice": "less_equal",
            "rhythm": "lt", "hidden": "less_int", "grammar": "is_int",
            "automata": "accept", "calendar": "less_int", "geometry": "segments_meet",
            "kitchen": "eq", "melody": "eq", "molecules": "value_less",
            "permutation": "contains", "pixels": "cell", "roads": "pair_before",
            "computer": "lt",
            "shadows": "same", "text": "is_text",
        }
        assert expected[world.name] in varying, (world.name, varying)


@pytest.mark.parametrize("module", (lists, grammar))
def test_fixed_field_tags_normalize_without_changing_published_declaration(module):
    original = module.world.decl()
    normalized = generator_decl(original)
    assert original.objects == module.world.decl().objects
    for old, new in zip(original.objects, normalized.objects):
        for tag, fields in (old.tags or {}).items():
            if (old.form == "compose" and isinstance(fields, dict)
                    and set(fields) != {"items"}):
                assert new.tags[tag] == [list(item) for item in fields.items()]
            else:
                assert new.tags[tag] == fields
    assert state(module.gen_world()).library.scope().resolve(
        "cons" if module is lists else "make_draft") is not None


def test_variable_length_items_tags_remain_variable_length():
    declaration = grammar.world.decl()
    found = 0
    for original, normalized in zip(declaration.objects, generator_decl(declaration).objects):
        if original.tags:
            for tag, fields in original.tags.items():
                if isinstance(fields, dict) and set(fields) == {"items"}:
                    found += 1
                    assert normalized.tags[tag] == fields
    assert found > 0


def test_world_tags_prioritize_declaration_metadata():
    declaration = replace(lists.world.decl(), extra={"tags": {
        "domain": "resource", "star_kind": "combinator"},
        "open_kinds": ["operation", "combinator"]})
    tags = world_tags("lists", declaration)
    assert tags["domain"] == "resource"
    assert tags["star_kind"] == "combinator"
    assert tags["open_kinds"] == ["combinator", "operation"]


def test_pixels_probe_samples_all_grid_regions():
    world = pixels.gen_world()
    def mask(grid):
        return sum(1 << (3 * row_index + column_index)
                   for row_index, row in enumerate(grid.fields[0].fields)
                   for column_index, pixel in enumerate(row) if pixel == "#")

    assert all(value.sort == "grid" and len(value.fields[0].fields) == 3
               for value in world.truth_states)
    masks = {mask(value) for value in world.truth_states}
    assert 0 in masks and 511 in masks
    assert all(1 << index in masks for index in range(9))
    assert len(world.sorts["point"].values) == 9
    point = world.sorts["point"].values[0]
    scope = state(world).library.scope()
    assert {truth(call("cell", (grid, point), scope).outcome.value)
            for grid in world.truth_states} == {False, True}


@pytest.mark.parametrize("module", (calendar, geometry, kitchen, melody, molecules,
                                     permutation, pixels, roads, shadows, text))
def test_new_catalogue_world_domains_and_combinators(module):
    world = module.gen_world()
    assert len(world.truth_states) >= 20
    assert all(len(sort.values) >= 2 for sort in world.sorts.values())
    assert len(world.sorts["int"].values) >= 4
    scope = state(world).library.scope()
    for entry in world.decl.combinators["library"]:
        name = entry["name"] if isinstance(entry, dict) else entry
        assert scope.resolve(name) is not None, (world.name, name)
    assert world.tags["open_kinds"] == sorted(world.open_kinds)


@pytest.mark.parametrize("factory", (lists.gen_world, integer.gen_world, calendar.gen_world))
def test_measured_recursion_admits(factory):
    world = factory()
    assert world.decl.combinators["recursion"] == "measure"
    counter = n.Var("counter")
    if factory is calendar.gen_world:
        sort = "int"
        measure = counter
        check = n.Call("less_int", (counter, n.Lit(1)))
        next_value = n.Call("decrement", (counter,))
    else:
        sort = "list"
        measure = n.Call("length", (counter,))
        check = n.Call("is_empty", (counter,))
        next_value = n.Call("tail", (counter,))
    step = n.Call("add", (n.Lit(2), n.Call("loop", (next_value,))))
    loop = n.Rec("loop", ("counter",), n.Case(((n.Test(check), n.Lit(0)),), step),
                 (n.Var("arg0"),), measure)
    result = deep(admit, state(world), candidate("f901", (sort,), "int", loop))
    assert isinstance(result, Entry), (world.name, result)
    assert result.steps_max > 0


@pytest.mark.parametrize(("module", "sort", "measure", "step", "empty", "combine"), (
    (dice, "value", "length", "tail", "is_empty", "int_add"),
    (geometry, "List", "length", "tail", "empty", "add"),
    (kitchen, "int", None, "sub", "lt", "add"),
    (text, "List", "seq_length", "seq_tail", "seq_is_empty", "add"),
))
def test_catalogue_measured_recursion_admits(module, sort, measure, step, empty, combine):
    world = module.gen_world()
    assert world.decl.combinators["recursion"] == "measure"
    counter = n.Var("counter")
    check = (n.Call(empty, (counter,)) if measure else
             n.Call(empty, (counter, n.Lit(1))))
    next_value = (n.Call(step, (counter,)) if measure else
                  n.Call(step, (counter, n.Lit(1))))
    body = n.Case(((n.Test(check), n.Lit(0)),),
                  n.Call(combine, (n.Lit(2), n.Call("loop", (next_value,)))))
    loop = n.Rec("loop", ("counter",), body, (n.Var("arg0"),),
                 n.Call(measure, (counter,)) if measure else counter)
    result = deep(admit, state(world), candidate("f910", (sort,), "int", loop))
    assert isinstance(result, Entry), (world.name, result)
    assert result.steps_max > 0


@pytest.mark.parametrize("module", CATALOGUE)
def test_catalogue_given_combinators_are_in_scope(module):
    world = module.gen_world()
    scope = state(world).library.scope()
    for entry in world.decl.combinators["library"]:
        name = entry["name"] if isinstance(entry, dict) else entry
        assert scope.resolve(name) is not None, (world.name, name)


def test_catalogue_probe_signatures_match_kernel_arity():
    for module in (dice, rhythm, hidden, grammar, automata, integer):
        world = module.gen_world()
        atoms = {atom.name: atom for atom in world.atoms}
        for probe in world.probes:
            assert world.signatures[probe].arity == atoms[probe].arity
        assert len(world.truth_states) >= 20


def test_classic_binary_counter_hints_are_not_measures():
    for name in CLASSIC:
        world = classic.gen_world(name)
        for sort, counters in classic.COUNTERS.get(name, {}).items():
            assert not any(step == counters[0][0] for step, _ in world.measures.get(sort, ()))
            for step, literal, _ in counters:
                assert literal == 1
                assert step in world.signatures


def test_integer_catalogue_decisions_are_not_constant():
    world = integer.gen_world()
    assert integer.CATALOGUE_SOURCE.endswith("integer@2.json")
    assert world.decl.version == 2
    scope = state(world).library.scope()
    for name in ("lt", "le", "eq", "ne"):
        assert name in world.signatures
        outcomes = [call(name, (left, right), scope).outcome
                    for left, right in product(world.sorts["int"].values, repeat=2)]
        assert {truth(outcome.value) for outcome in outcomes} == {False, True}
    outcomes = [call("is_empty", (value,), scope).outcome
                for value in world.sorts["list"].values]
    assert {truth(outcome.value) for outcome in outcomes} == {False, True}


def test_rhythm_truth_covers_all_beats():
    world = rhythm.gen_world()
    assert len(set(world.truth_states)) == 24
    for index in range(8):
        assert {beat.fields[index] for beat in world.truth_states} == {0, 1, 2}


def test_text_recursion_scope_contains_empty_and_multiple_lengths():
    world = text.gen_world()
    scope = state(world).library.scope()
    lengths = {call("seq_length", (value,), scope).outcome.value
               for value in world.sorts["List"].values}
    assert {0, 1, 2} <= lengths
    assert world.measures["List"] == [("seq_tail", "seq_length")]


@pytest.mark.parametrize("factory", (lambda: classic.gen_world("action"), action.gen_world))
def test_robot_truth_probes_are_balanced(factory):
    world = factory()
    scope = state(world).library.scope()
    names = ("front_wall", "front_water", "holding") if world.dialect == "legacy-v1" else (
        "front_wall", "front_water")
    for name in names:
        outcomes = [call(name, (sample,), scope, dialect=world.dialect).outcome
                    for sample in world.truth_states]
        assert all(isinstance(outcome, Ok) for outcome in outcomes)
        share = sum(truth(outcome.value) for outcome in outcomes) / len(outcomes)
        assert 0.2 <= share <= 0.8, (world.name, name, share)
    if world.dialect == "legacy-v1":
        assert {sample.facing for sample in world.truth_states} == {"N", "E", "S", "W"}
        heights = [call("front_height", (sample,), scope, dialect=world.dialect).outcome.value
                   for sample in world.truth_states]
        assert len(set(heights)) >= 4


def test_hidden_judge_probe_is_not_granted_to_generator():
    world = hidden.gen_world()
    assert world.probes == ("receiver",)
    assert "judge" not in world.signatures
    assert state(world).library.scope().resolve("judge") is None
    assert any(probe["name"] == "judge" for probe in world.decl.observation["probes"])


def test_catalogue_has_an_adapter_for_every_declared_world():
    root = Path(__file__).resolve().parents[2] / "worlds/decl/v2"
    assert {path.stem.split("@")[0] for path in root.glob("*.json")} == {
        module.__name__.rsplit(".", 1)[-1] for module in CATALOGUE}


def test_declared_tags_and_open_kinds_override_defaults():
    declaration = replace(lists.world.decl(), extra={"tags": {
        "domain": "resource", "star_kind": "combinator"},
        "open_kinds": ["operation", "combinator"]})
    assert world_tags("lists", declaration)["domain"] == "resource"
    assert world_tags("lists", declaration)["star_kind"] == "combinator"
    assert generator_decl(declaration).open_kinds == ("combinator", "operation")


@pytest.mark.parametrize("module", CATALOGUE)
def test_catalogue_domains_and_typed_scope(module):
    world = module.gen_world()
    library = state(world).library
    scope = library.scope()
    assert world.dialect == "atoms-v2"
    assert world.open_kinds == frozenset(world.decl.open_kinds)
    assert world.tags["open_kinds"] == sorted(world.open_kinds)
    assert world.tags["star_kind"] in world.open_kinds
    assert all(len(sort.values) >= 2 for sort in world.sorts.values())
    assert len(world.truth_states) >= 20
    for name, signature in world.signatures.items():
        assert scope.resolve(name) is not None, (world.name, name)
        assert all(sort in world.sorts for sort in (*signature.inputs, signature.output))
    for name in world.probes:
        assert scope.resolve(name).kind == "observation", (world.name, name)
    for entry in world.decl.combinators.get("library", ()):
        name = entry["name"] if isinstance(entry, dict) else entry
        assert scope.resolve(name) is not None, (world.name, name)
        definition = library.get(name)
        assert definition.kind == "combinator", (world.name, name)
        assert definition.body == scope.resolve(name).body, (world.name, name)


@pytest.mark.parametrize("name", CLASSIC)
def test_legacy_worlds_remain_operation_only(name):
    world = classic.gen_world(name)
    assert world.open_kinds == frozenset({"operation"})
    assert world.dialect == "legacy-v1"
    assert state(world).library.scope()


@pytest.mark.parametrize("module", CATALOGUE)
def test_adapter_tags_match_declared_metadata(module):
    world = module.gen_world()
    declaration = module.world.decl() if hasattr(module, "world") else world.decl
    assert world.tags == world_tags(world.name, declaration)
    assert world.title


@pytest.mark.parametrize("module", (action, circuits, hidden, automata, permutation))
def test_deep_world_public_probes_have_valid_samples(module):
    world = module.gen_world()
    scope = state(world).library.scope()
    for name in world.probes:
        signature = world.signatures[name]
        domains = [world.sorts[sort].values for sort in signature.inputs[1:]]
        valid = []
        for extra in product(*(domain[:4] for domain in domains)):
            valid.extend(call(name, (sample, *extra), scope).outcome
                         for sample in world.truth_states[:24])
        assert any(isinstance(outcome, Ok) for outcome in valid), (world.name, name)
    assert all(not isinstance(value, Bottom) for value in world.truth_states)


def test_action_maze_walls_water_and_public_poses():
    world = action.gen_world()
    scope = state(world).library.scope()
    assert {sample.fields[0] for sample in world.truth_states} <= {
        action_hosts.maze(name) for name in action_hosts.MAPS}
    for name in ("front_wall", "front_water"):
        results = [truth(call(name, (sample,), scope).outcome.value)
                   for sample in world.truth_states]
        assert 0.2 <= sum(results) / len(results) <= 0.5
    assert all(call("pose", (sample,), scope).outcome.value.sort == "Pose"
               for sample in world.truth_states)
    assert {value.sort for value in world.sorts["unknown"].values
            if hasattr(value, "sort")} >= {"Known", "Scan"}


def test_action_given_sequence_uses_the_declared_composition():
    world = action.gen_world()
    scope = state(world).library.scope()
    bot = world.truth_states[0]
    result = call("seq", (FnRef("turn_left"), FnRef("turn_right"), bot), scope).outcome
    assert isinstance(result, Ok)
    assert result.value.fields[:4] == bot.fields[:4]


@pytest.mark.parametrize(("module", "sort", "operation", "extra", "output"), (
    (action, "Bot", "turn_right", (), "Bot"),
    (automata, "word", "char_tail", (), "word"),
    (circuits, "int", "integer_add", (1,), "int"),
    (permutation, "permutation", "swap", (1, 2), "permutation"),
    (hidden, "int", "decrease", (1,), "int"),
))
def test_priority_worlds_admit_layer_one_compositions(module, sort, operation, extra, output):
    world = module.gen_world()
    signature = world.signatures[operation]
    assert sort in signature.inputs and signature.output == output
    variable = n.Var("arg0")
    if module is permutation:
        inner = n.Call(operation, (n.Lit(1), n.Lit(2), variable))
        body = n.Call(operation, (n.Lit(2), n.Lit(3), inner))
    else:
        inner = n.Call(operation, (variable, *(n.Lit(value) for value in extra)))
        body = n.Call(operation, (inner, *(n.Lit(value) for value in extra)))
    spec = OperationSpec("f910", "transform", (Edge(sort),), Edge(output),
                         "Compose two given actions.")
    candidate = Candidate(Definition("f910", "operation", "invented", 1,
                                     tuple(sorted(n.references(body))), spec, body),
                          Signature((sort,), output), "test.world")
    assert isinstance(admit(state(world), candidate), Entry)


def test_declaration_combinators_are_resolvable_without_fabricated_bodies():
    for module, name in ((molecules, "chain"), (pixels, "then"), (action, "seq")):
        world = module.gen_world()
        assert state(world).library.scope().resolve(name) is not None


def test_automata_accepts_typed_words_and_varied_machines():
    world = automata.gen_world()
    scope = state(world).library.scope()
    assert world.signatures["accept"].inputs == ("automaton", "word")
    assert {truth(call("accept", (machine, word), scope).outcome.value)
            for machine in world.truth_states for word in ("", "a", "b", "ab")} == {False, True}
    assert all(automata_hosts.machine_valid(machine) for machine in world.truth_states)


def test_circuits_evaluate_bits_at_output_pins():
    world = circuits.gen_world()
    scope = state(world).library.scope()
    assert all(circuit_hosts.circuit_valid(circuit) for circuit in world.truth_states)
    assert world.signatures["out_pin"].inputs == ("circuit", "bits", "int")
    assert {call("out_pin", (circuit, bits, 0), scope).outcome.value
            for circuit in world.truth_states
            for bits in world.sorts["bits"].values} == {0, 1}


def test_permutation_samples_are_twelve_card_bijections():
    world = permutation.gen_world()
    assert all(permutation_hosts.valid_permutation(sample) for sample in world.truth_states)
    assert len({repr(sample) for sample in world.truth_states}) >= 20


def test_geometry_points_probe_feeds_list_operations():
    world = geometry.gen_world()
    scope = state(world).library.scope()
    assert world.signatures["points"] == Signature(("Path",), "List")
    assert world.decl.observation["probes"][0]["sort"] == "List"
    result = call("points", (world.truth_states[0],), scope).outcome
    assert isinstance(result, Ok)
    assert call("length", (result.value,), scope).outcome == Ok(len(result.value))


def test_roads_truth_domain_matches_public_graph_cards():
    world = roads.gen_world()
    assert world.decl.observation["truth"] == world.truth_sort == "Roads"
    assert world.probes == ("map_view",)
    assert world.signatures["size"] == Signature(("List",), "int")
    assert all(sample.sort == "Roads" for sample in world.truth_states)
    assert all(world.signatures[name].inputs == ("Roads",) for name in world.probes)


def test_hidden_truth_remains_sealed_behind_receiver():
    world = hidden.gen_world()
    scope = state(world).library.scope()
    assert world.probes == ("receiver",)
    assert "judge" not in world.signatures
    assert scope.resolve("judge") is None
    assert {sample.fields[0] for sample in world.truth_states} == {"R", "B"}
    views = {card: call("receiver", (card,), scope).outcome.value
             for card in world.truth_states}
    assert any(views[left] == views[right] for left in views for right in views
               if left.fields[0] != right.fields[0])


def test_fixed_field_tags_are_normalized_without_changing_the_declaration():
    declaration = action.world.decl()
    normalized = generator_decl(declaration)
    assert declaration.objects != normalized.objects
    for original, copied in zip(declaration.objects, normalized.objects):
        for tag, fields in (original.tags or {}).items():
            if isinstance(fields, dict) and set(fields) != {"items"}:
                assert copied.tags[tag] == [list(item) for item in fields.items()]
            else:
                assert copied.tags[tag] == fields


def test_variadic_tags_remain_variadic():
    declaration = circuits.world.decl()
    normalized = generator_decl(declaration)
    variadic = [(original, copied) for original, copied in
                zip(declaration.objects, normalized.objects)
                if any(isinstance(fields, dict) and set(fields) == {"items"}
                       for fields in (original.tags or {}).values())]
    assert variadic
    for original, copied in variadic:
        assert copied.tags == original.tags


def test_closed_boolean_sort_has_exhaustive_probe_domain():
    for module in (action, circuits, hidden, permutation):
        assert module.gen_world().sorts["bool"].finite
    assert action.gen_world().sorts["Maze"].finite
    assert circuits.gen_world().sorts["bit"].finite


@pytest.mark.parametrize("module", CATALOGUE)
def test_every_declared_probe_has_an_executable_domain(module):
    world = module.gen_world()
    scope = state(world).library.scope()
    for name in world.probes:
        signature = world.signatures[name]
        domains = [world.sorts[sort].values[:6] for sort in signature.inputs]
        assert any(isinstance(call(name, arguments, scope).outcome, Ok)
                   for arguments in product(*domains)), (world.name, name)


def test_world_installed_handles_a_missing_parent_package():
    assert configs.world_installed("opulse.gen_v2.configs")
    assert not configs.world_installed("opulse.worlds_v2.no_such_world_package.world")
