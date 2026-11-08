"""Rhythm layer-zero declaration and host atoms."""

import json
from dataclasses import replace
from functools import partial
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.check import check_definition
from opulse.atoms.combinators import check_combinator
from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object
from opulse.atoms.spec import Edge, OperationSpec
from opulse.atoms.values import Bottom
from opulse.atoms.world import WorldDecl

from . import hosts


def decl():
    path = Path(__file__).resolve().parents[4] / 'worlds/decl/v2/rhythm@1.json'
    return WorldDecl.from_dict(json.loads(path.read_text(encoding='utf-8')))


def checked_call(name, *args):
    return (getattr(hosts, name)(*args) if all(hosts.valid_value(arg) for arg in args)
            else Bottom('invalid'))


def atoms():
    world = decl()
    return [Atom(op.name, len(op.inputs), partial(checked_call, op.name), op.cost)
            for op in world.operations] + [
                Atom(probe['name'], 1, partial(checked_call, 'cells'), 1, kind='observation')
                for probe in world.observation['probes']]


def new_library():
    class RhythmLibrary(Library):
        def run(self, name, args, fuel=None, trace=False):
            if any(not hosts.valid_value(arg) for arg in args):
                outcome = Bottom('invalid')
                node = (kernel.CallNode(None, 'root', 0, False, (), (), outcome, 0)
                        if trace else None)
                return kernel.Run(outcome, 0, 0, node)
            return super().run(name, args, fuel=fuel, trace=trace)

        def check(self, name):
            if name == 'offbeat':
                return super().check(name)
            definition = self.get(name)
            problems = [problem for problem in check_definition(definition, self.world,
                         lambda reference: self.definitions.get(reference) or self.scope().resolve(reference))
                        if ' argument ' not in problem]
            if definition.kind == 'combinator':
                problems += check_combinator(definition, self)
            if definition.kind == 'object':
                problems += check_object(definition, self)
            if problems:
                raise PipelineError(problems)
            return self._advance(name, 'checked')

    library = RhythmLibrary(decl(), atoms())
    probe = library.get('cells')
    library._definitions['cells'] = replace(probe, spec=OperationSpec('cells', 'relate',
        (Edge('any'),), Edge('list'), 'Public full-cell probe.'))
    return library
