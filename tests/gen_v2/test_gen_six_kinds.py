"""Core records for generator laws and bridges, including replay and export."""

from dataclasses import replace

from opulse.atoms import nodes
from opulse.atoms.laws import replay_rewrite, rewrite
from opulse.atoms.library import atoms_digest
from opulse.atoms.spec import BridgeSpec, Definition, LawSpec, ObservationSpec
from opulse.atoms.values import Bottom
from opulse.gen_v2 import laws
from opulse.gen_v2.admit import admit
from opulse.gen_v2.audit import audit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.bridges import admit_proposed, propose
from opulse.gen_v2.export import export
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.bridge import candidate as bridge_candidate
from opulse.gen_v2.moves.law import candidate as law_candidate
from opulse.gen_v2.moves.operation import MOVES as OPERATION_MOVES
from opulse.gen_v2.notation import parse_declaration, print_declaration, tokens
from opulse.gen_v2.run import generate, load, save
from opulse.gen_v2.worlds import toy, toy_truth


def test_law_record_pipeline_and_exact_replay(tmp_path):
    world = toy.gen_world(("operation", "law"))
    state = generate(world, 5, 9, per_kind_min=0, layer_target=1,
                     moves=OPERATION_MOVES[:3])
    discovered = laws.discover(state, 3, seed=9)
    assert discovered
    item = law_candidate(state, discovered[0])
    result = admit(state, item)
    assert isinstance(result, Entry), result
    record = state.library.get(result.name)
    assert isinstance(record.spec, LawSpec) and record.status == "promoted"
    assert record.evidence.atoms_hash == atoms_digest(state.library.atoms)
    assert "holds" in record.evidence.checks
    assert record.evidence.scope["size"] == len(state.requests[result.name].domain)
    assert record.spec.equation is not None
    before, _ = record.spec.equation
    after = rewrite(before, record, state.library)
    environment = dict(zip((name for name, _ in record.spec.vars),
                           state.requests[result.name].domain[0]))
    derivation = replay_rewrite(before, after, f"#{result.name}", state.library, environment)
    assert len(derivation.steps) == 1
    assert derivation.steps[0].law == result.name
    text = print_declaration(result, state)
    assert parse_declaration(text, state)["name"] == result.name
    assert any(token["kind"] == "law" and token["name"] == result.name
               for token in tokens(text, state))
    assert audit(state).ok
    law_steps = list(state.library._steps[result.name])
    assert law_steps
    state.library._steps[result.name] = []
    assert any(failure.name == result.name and failure.invariant == "I1"
               for failure in audit(state).failures)
    state.library._steps[result.name] = law_steps
    assert export(state, tmp_path / "six.json")["entries"][-1]["ascii"].isascii()
    save(state, tmp_path / "six-checkpoint.json")
    restored = load(world, tmp_path / "six-checkpoint.json")
    assert isinstance(restored.library.get(result.name).spec, LawSpec)


def test_false_law_never_promotes():
    world = toy.gen_world(("operation", "law"))
    state = generate(world, 3, 9, per_kind_min=0, layer_target=1,
                     moves=OPERATION_MOVES[:3])
    first = next(entry for entry in state.entries.values() if entry.signature.output == "int")
    variables = tuple((f"v{index}", sort) for index, sort in enumerate(first.signature.inputs))
    call = nodes.Call(first.name, tuple(nodes.Var(name) for name, _ in variables))
    statement = nodes.Call("eq", (call, nodes.Lit(10**9)))
    law = laws.LawRecord("", statement, variables, ("eq", first.name), first.layer + 1)
    item = law_candidate(state, law)
    assert item is not None
    result = admit(state, item)
    assert result.stage in ("verify", "callable")
    assert item.defn.name not in state.entries


def test_discovery_and_bridge_admission_helpers():
    world = toy.gen_world(("operation", "law"))
    state = generate(world, 5, 9, per_kind_min=0, layer_target=1,
                     moves=OPERATION_MOVES[:3])
    admitted = laws.admit_discovered(state, 4, seed=9)
    assert admitted and all(isinstance(state.library.get(entry.name).spec, LawSpec)
                            for entry in admitted)


def test_bridge_record_commuting_and_audit(tmp_path):
    from test_gen_bridges import _add_record, _state

    state = _state(toy)
    state.world = replace(state.world, decl=replace(state.world.decl,
                          open_kinds=(*state.world.decl.open_kinds, "bridge")),
                          open_kinds=frozenset((*state.world.open_kinds, "bridge")))
    state.library = type(state.library)(state.world.decl, state.world.atoms,
                                         state.world.dialect, state.world.extra_scope,
                                         state.world.signatures)
    _add_record(state, "A1", "f1")
    assert state.layer("A1.value") == state.entries["A1"].layer
    assert state.library.get("f1").layer == state.entries["A1"].layer + 1
    assert admit_proposed(state, max_bridges=0) == []
    bridge = next(item for item in propose(state, max_bridges=20, seed=19)
                  if ("f1", "inc") in item.interface and item.source[1] == "A1")
    guarded = (bridge.domain[0], next(value for value in bridge.domain
                                      if value.fields[0] == bridge.domain[0].fields[0] + 1
                                      and value.fields[1] == bridge.domain[0].fields[1]))
    partial = bridge_candidate(state, replace(bridge, domain=guarded))
    assert partial is not None and partial.defn.spec.domain is not None
    assert isinstance(admit(state, partial), Entry)
    assert state.library.run(partial.defn.name, (bridge.domain[1],)).outcome == Bottom("outside_domain")
    item = bridge_candidate(state, bridge)
    assert item is not None
    result = admit(state, item)
    assert isinstance(result, Entry), result
    record = state.library.get(result.name)
    assert isinstance(record.spec, BridgeSpec) and record.status == "promoted"
    assert "commutes" in record.evidence.checks
    text = print_declaration(result, state)
    assert parse_declaration(text)["source"] == "A1"
    assert any(token["kind"] == "bridge" and token["name"] == result.name
               for token in tokens(text, state))
    assert audit(state).ok
    original_steps = list(state.library._steps[result.name])
    assert original_steps
    state.library._steps[result.name] = []
    assert any(failure.name == result.name and failure.invariant == "I1"
               for failure in audit(state).failures)
    state.library._steps[result.name] = original_steps
    assert any(entry["ascii"].startswith("bridge ~") for entry in
               export(state, tmp_path / "bridges.json")["entries"])
    save(state, tmp_path / "bridge-checkpoint.json")
    restored = load(state.world, tmp_path / "bridge-checkpoint.json")
    assert isinstance(restored.library.get(result.name).spec, BridgeSpec)
    assert audit(restored).ok


def test_observation_without_independent_reference_promotes_on_generator_checks():
    world = toy_truth.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    body = nodes.Call("add", (nodes.Var("read_x"), nodes.Lit(1)))
    definition = Definition("q401", "observation", "invented", 1, ("add",),
                            ObservationSpec("q401", ("read_x",), body), body)
    result = admit(state, Candidate(definition, Signature(("truth",), "int"), "obs.no_oracle"))
    assert isinstance(result, Entry), result
    evidence = state.library.get("q401").evidence
    assert evidence.scope["reference"] == "none"
    assert set(evidence.checks) == {"dependency", "facts_unchanged", "non_interference",
                                    "unfold_equivalence"}
    assert "reference" not in evidence.checks


def test_observation_without_non_interference_cannot_promote():
    from dataclasses import replace as replace_record

    from opulse.atoms.library import PipelineError
    from opulse.atoms.spec import Contract

    world = toy_truth.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    body = nodes.Call("add", (nodes.Var("read_x"), nodes.Lit(1)))
    definition = Definition("q401", "observation", "invented", 1, ("add",),
                            ObservationSpec("q401", ("read_x",), body), body)
    result = admit(state, Candidate(definition, Signature(("truth",), "int"), "obs.no_oracle"))
    assert isinstance(result, Entry), result
    library = state.library
    record = library.get(result.name)
    library._definitions[result.name] = replace_record(
        record, status="verified", contract=None,
        evidence=replace_record(record.evidence, checks=tuple(
            check for check in record.evidence.checks if check != "non_interference")))
    try:
        library.promote(result.name, Contract(guarantees="verified"))
    except PipelineError as error:
        assert "non_interference" in str(error)
    else:
        raise AssertionError("promotion accepted missing non_interference")
