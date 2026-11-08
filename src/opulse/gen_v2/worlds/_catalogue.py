"""Shared catalogue bridge for given combinators and finite typed probe domains."""

from opulse.gen_v2.worlds._common import build


def catalogue(name, world, values, **options):
    return build(name, world.decl(), world.atoms(), values, **options)
