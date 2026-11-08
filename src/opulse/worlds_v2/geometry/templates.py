"""A bounded family of canonical regions under lattice symmetry groups."""

from dataclasses import replace

from opulse.atoms import nodes as n
from opulse.atoms.library import bounded
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.templates import instantiate

from .story import call, lit, reference_region, region_card, small_region_family, var

FAMILY = [
    {"T": "Region", "group": "_normalize"},
    {"T": "Region", "group": "_dihedral_normalize"},
]
INSTANCES = ("TranslationCanon", "DihedralCanon")


def install_templates(library):
    from worlds.catalogue.depth import geometry as reference

    def independent_dihedral(region):
        outer, holes = reference.signature(reference_region(region))
        return region_card(reference.Region(reference.Ring(*outer),
                                            tuple(reference.Ring(*hole) for hole in holes)))

    dihedral_body = call("Signature.base", call("Signature.make", var("r")))
    dihedral = Definition(
        "_dihedral_normalize", "operation", "invented", 9,
        ("Signature.make", "Signature.base"),
        OperationSpec("_dihedral_normalize", "transform", (Edge("Region"),), Edge("Region"),
                      "Canonical region among the eight dihedral images after translation.",
                      extra={"input_names": ["r"]}), dihedral_body,
    )
    scalene = reference.Region(reference.Ring((4, 3), (7, 3), (4, 5)))
    domain = tuple(region_card(region) for region in (*small_region_family()[:2], scalene))
    description = "bounded to two translated isosceles triangles and one scalene triangle in the 0..32 lattice"
    library.write(dihedral)
    library.check(dihedral.name)
    library.make_callable(dihedral.name, ((domain[0],),))
    library.verify(dihedral.name, replace(
        bounded((domain,), description),
        reference=independent_dihedral,
    ))
    library.account(dihedral.name)
    library.promote(dihedral.name, Contract("Exact on the three recorded triangles."))

    valid = call("eq", call("Region.make", call("Region.base", var("x"))), var("x"))
    template = Definition(
        "Canon", "template", "invented", 1, (),
        TemplateSpec("Canon", (("T", "sort"), ("group", "operation")), "object", {
            "form": "refine", "base": "$T", "valid": n.to_json(valid),
            "canon": n.to_json(call("$group", var("x"))), "params": ["x"],
            "sealed": False, "interface": [],
            "definition_body": n.to_json(n.Let("accepted", valid, call("$group", var("x")))),
        }, {"family": FAMILY}), lit("Canon[T, group]"),
    )
    member_requests = tuple(bounded((domain,), description)
                            for _ in FAMILY)
    request = replace(bounded((tuple((entry["T"], entry["group"]) for entry in FAMILY),),
                              "bounded to 2 canonical-region families: translation and dihedral"),
                      scope={"domain": "bounded to 2 canonical-region families: translation and dihedral",
                             "size": len(FAMILY), "family": FAMILY},
                      extra={"family": FAMILY, "member_requests": member_requests})
    library.write(template)
    library.check(template.name)
    library.make_callable(template.name, (("Region", "_normalize"),))
    library.verify(template.name, request)
    library.account(template.name)
    library.promote(template.name, Contract("Exact on the two recorded symmetry families."))
    for name, arguments, member_request in zip(INSTANCES, FAMILY, member_requests):
        member = instantiate(library.get("Canon"), arguments, name, lib=library)
        library.write(member)
        library.check(name)
        library.make_callable(name, member_request.domain)
        library.verify(name, member_request)
        library.account(name)
        library.promote(name, Contract("Exact for the three recorded triangular regions."))
