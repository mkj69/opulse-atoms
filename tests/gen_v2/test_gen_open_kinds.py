"""Seeded generation stays within each world's declared open kinds."""

import pytest

from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import (
    comb_obs,
    comb_only,
    obj_only,
    obj_op,
    obs_only,
    op_only,
)


@pytest.mark.parametrize("module", (op_only, obs_only, obj_only, comb_only, comb_obs, obj_op))
def test_seeded_run_invents_only_open_kinds(module):
    world = module.gen_world()
    assert world.open_kinds == frozenset(module.world.decl().open_kinds)
    state = generate(world, target=1, seed=3, per_kind_min=0, layer_target=0, time_limit=5)
    assert state.entries, (world.name, state.rejections[-5:])
    assert all(entry.kind in world.open_kinds for entry in state.entries.values())


def test_obs_only_keeps_the_sealed_state_as_truth():
    """Round 6 review: the adapter must not replace the sealed State truth by its public Trace."""
    from opulse.worlds_v2.obs_only import hosts, model

    world = obs_only.gen_world()
    assert world.truth_sort == obs_only.world.decl().observation["truth"] == "State"
    assert len(world.truth_states) >= 20
    assert all(isinstance(state, model.State) for state in world.truth_states)
    probes = {atom.name: atom for atom in world.atoms if atom.name in world.probes}
    state = world.truth_states[3]
    assert probes["frame"].fn(state, 0) == hosts.frame(state.history, 0)
    assert probes["prior"].fn(state, 5) == hosts.prior(hosts.public_config(state.history), 5)
