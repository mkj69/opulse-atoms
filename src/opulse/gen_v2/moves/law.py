"""Propose scoped laws about operations already admitted in this world."""

import itertools
from dataclasses import dataclass

from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Definition, LawSpec
from opulse.gen_v2 import laws
from opulse.gen_v2.base import Candidate


def candidate(state, law):
    domains = laws._domains(state, law)
    if not domains:
        return None
    values = [domains[sort] for _, sort in law.vars]
    bound = max(1, state.world.max_scope)
    while laws.size_of(len(items) for items in values) > bound:
        index = max(range(len(values)), key=lambda item: len(values[item]))
        if len(values[index]) <= 1:
            return None
        values[index] = values[index][:-1]
    domain = tuple(itertools.product(*values))
    finite = (all(state.sorts[sort].finite and len(domains[sort]) == len(state.sorts[sort].values)
                  for _, sort in law.vars) and
              all(laws._exhaustive_dependency(state, ref) for ref in law.depends_on
                  if ref in state.entries) and
              laws.size_of(len(items) for items in values) ==
              laws.size_of(len(state.sorts[sort].values) for _, sort in law.vars))
    description = ("all values" if finite else "bounded prefixes of the declared sort probes")
    request = VerifyRequest("exhaustive" if finite else "bounded", domain,
                            {"domain": description, "size": len(domain),
                             "variables": [[name, sort] for name, sort in law.vars],
                             "values": {name: [laws.encode_value(item) for item in items]
                                        for (name, _), items in zip(law.vars, values)}})
    name = state.names.fresh("law")
    spec = LawSpec(name, law.vars, law.statement)
    definition = Definition(name, "law", "invented", law.layer, law.depends_on, spec, law.statement)
    return Candidate(definition, None, "law.conjecture", request,
                     contract="The statement holds on every input of the recorded scope.")


@dataclass
class LawMove:
    kind: str = "law"
    name: str = "law.conjecture"

    def __call__(self, state, rng):
        if not state.entries:
            return None
        names = [entry.name for entry in state.entries.values() if entry.kind == "operation"]
        if not names:
            return None
        for law in itertools.islice(laws.conjecture(state, rng.choice(names)), 12):
            if laws.check(state, law, bound=min(256, max(1, state.world.max_scope))) is None:
                continue
            result = candidate(state, law)
            if result is not None:
                return result
        return None


MOVES = [LawMove()]
