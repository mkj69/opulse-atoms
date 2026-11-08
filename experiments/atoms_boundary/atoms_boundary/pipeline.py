"""Shared AML definition and evidence pipeline for both boundary towers."""

from dataclasses import replace
from types import SimpleNamespace

from atoms_mul.kernel import parse_program
from atoms_mul.kernel.core_library import compile_definition

from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Contract


def promote_tower(library, source, domains, references, descriptions, contracts,
                  memoized=()):
    """Promote AML entries and selected memo bodies on their own recorded domains."""
    lookup = {}
    for entry in parse_program(source).defs:
        definition = compile_definition(entry, lookup)
        if definition is None:
            raise ValueError(f"mutual recursion in {entry.name}")
        _promote(library, definition, domains[entry.name], references[entry.name],
                 descriptions[entry.name], contracts[entry.name])
        lookup[entry.name] = SimpleNamespace(name=entry.name, body=entry.body,
                                             layer=library.get(entry.name).layer)
        if entry.name in memoized:
            name = f"{entry.name}_memo"
            variant = replace(definition, name=name, spec=replace(definition.spec, name=name),
                              body=replace(definition.body, memo=True))
            _promote(library, variant, domains[entry.name], references[entry.name],
                     descriptions[entry.name], contracts[entry.name])
    return library


def _promote(library, definition, domain, reference, description, contract):
    name = definition.name
    library.write(definition)
    library.check(name)
    library.make_callable(name, domain[:1])
    library.verify(name, VerifyRequest(
        "exhaustive", domain, {"domain": description, "size": len(domain)},
        reference=reference,
    ))
    library.account(name)
    library.promote(name, Contract(contract))
