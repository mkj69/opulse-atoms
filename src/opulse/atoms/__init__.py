"""atoms-v2: six kinds of atoms, one definition pipeline (docs/spec/atoms-v2.md).

This package is an optional extension. The existing operator pipeline keeps working
unchanged; it is the special case ``dialect: legacy-v1`` (spec section 13).
"""

SPEC_VERSION = "atoms-v2/0.5"
KINDS = ("object", "operation", "combinator", "observation", "law", "bridge")  # the six kinds (spec 0.4)
LAYER0_KINDS = KINDS[:4]  # what layer 0 of a world declares; laws may also be given as axioms
