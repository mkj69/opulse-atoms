"""Layer-zero host predicates for legacy declarations (specification section 4)."""

NAMES = frozenset(("Ana", "Bo", "Cora", "Dev", "Eli", "Faye", "Gio", "Hana",
                   "Ivo", "Jae", "Kira", "Luz"))


def valid_person(value: object) -> bool:
    return type(value) is str and value in NAMES


def valid_colour(value: object) -> bool:
    return type(value) is int and 0 <= value <= 9


def valid_note(value: object) -> bool:
    return type(value) is int and 0 <= value <= 127
