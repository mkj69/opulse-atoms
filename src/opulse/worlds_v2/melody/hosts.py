"""Given melody actions and generic finite-list/number primitives."""

from functools import wraps

from opulse.atoms.values import Bottom, Card, boolean


def valid_melody(value):
    return (isinstance(value, Card) and value.sort == "Melody" and value.tag == "events"
            and 1 <= len(value.fields) <= 64
            and all(type(event) is tuple and len(event) == 2 and type(event[0]) is int
                    and 48 <= event[0] <= 84 and type(event[1]) is int
                    and 1 <= event[1] <= 4 for event in value.fields))


def valid_motif(value):
    if (not isinstance(value, Card) or value.sort != "Motif" or value.tag != "val"
            or len(value.fields) != 1 or type(value.fields[0]) is not tuple):
        return False
    steps = value.fields[0]
    return (2 <= len(steps) <= 8 and type(steps[0]) is tuple and len(steps[0]) == 2
            and type(steps[0][0]) is int and steps[0][0] == 0
            and all(type(step) is tuple and len(step) == 2 and type(step[0]) is int
                    and -36 <= step[0] <= 36 and type(step[1]) is int
                    and 1 <= step[1] <= 4 for step in steps))


def valid_score(value):
    if (not isinstance(value, Card) or value.sort != "Score" or value.tag != "val"
            or len(value.fields) != 1 or type(value.fields[0]) is not tuple
            or len(value.fields[0]) != 2):
        return False
    source, motifs = value.fields[0]
    return (valid_melody(source) and type(motifs) is tuple and 1 <= len(motifs) <= 12
            and all(valid_motif(item) for item in motifs)
            and len(set(motifs)) == len(motifs))


def valid_cards(value):
    if isinstance(value, Card):
        if value.sort == "Melody":
            return valid_melody(value)
        if value.sort == "Motif":
            return valid_motif(value)
        if value.sort == "Score":
            return valid_score(value)
        return value.sort == "bool" and value.tag in ("true", "false") and not value.fields
    if type(value) in (tuple, list):
        return all(valid_cards(item) for item in value)
    if type(value) is dict:
        return all(valid_cards(key) and valid_cards(item) for key, item in value.items())
    if type(value) in (set, frozenset):
        return all(valid_cards(item) for item in value)
    return True


def melody(*events):
    value = Card("Melody", "events", tuple(events))
    return value if valid_melody(value) else Bottom("invalid")


def to_card(value):
    if not valid_melody(value):
        raise ValueError("invalid melody")
    return value


def from_card(value):
    return to_card(value)


def note_shift(event, semitones):
    if type(semitones) is not int or not -12 <= semitones <= 12:
        return Bottom("range")
    if (type(event) is not tuple or len(event) != 2 or type(event[0]) is not int
            or type(event[1]) is not int or event[1] not in (1, 2, 3, 4)):
        return Bottom("event")
    pitch, duration = event
    if not 48 <= pitch + semitones <= 84:
        return Bottom("pitch")
    return pitch + semitones, duration


def transpose(source, semitones):
    if type(semitones) is not int or not -12 <= semitones <= 12:
        return Bottom("range")
    if not valid_melody(source):
        return Bottom("invalid")
    shifted = tuple(note_shift(event, semitones) for event in source.fields)
    for event in shifted:
        if isinstance(event, Bottom):
            return event
    return melody(*shifted)


def slice_events(source, start, length):
    if not valid_melody(source) or type(start) is not int or type(length) is not int:
        return Bottom("invalid")
    if not 0 <= start <= 63 or not 0 <= length <= 64:
        return Bottom("range")
    if length < 1 or start + length > len(source.fields):
        return Bottom("slice")
    return melody(*source.fields[start:start + length])


def concat(left, right):
    if not valid_melody(left) or not valid_melody(right):
        return Bottom("invalid")
    if len(left.fields) + len(right.fields) > 64:
        return Bottom("capacity")
    return melody(*left.fields, *right.fields)


def events(source):
    return source.fields if valid_melody(source) else Bottom("invalid")


def beats(source):
    if isinstance(source, Card) and source.sort == "Score":
        if not valid_score(source):
            return Bottom("invalid")
        source = source.fields[0][0]
    notes = events(source)
    return notes if isinstance(notes, Bottom) else sum(event[1] for event in notes)


def score_view(source):
    return source if valid_score(source) else Bottom("invalid")


def list_length(items):
    return len(items) if type(items) is tuple else Bottom("invalid")


def list_get(items, index):
    if type(items) is not tuple or type(index) is not int:
        return Bottom("invalid")
    return items[index] if 0 <= index < len(items) else Bottom("range")


def list_slice(items, start, end):
    if type(items) is not tuple or type(start) is not int or type(end) is not int:
        return Bottom("invalid")
    return items[start:end] if 0 <= start <= end <= len(items) else Bottom("range")


def list_cons(item, items):
    return (item, *items) if type(items) is tuple else Bottom("invalid")


def list_append(items, item):
    return (*items, item) if type(items) is tuple else Bottom("invalid")


def list_unique(items):
    if type(items) is not tuple:
        return boolean(False)
    try:
        return boolean(len(set(items)) == len(items))
    except TypeError:
        return boolean(False)


def list_contains(items, item):
    return boolean(type(items) is tuple and item in items)


def pair(left, right):
    return left, right


def first(value):
    return value[0] if type(value) is tuple and len(value) == 2 else Bottom("invalid")


def second(value):
    return value[1] if type(value) is tuple and len(value) == 2 else Bottom("invalid")


def add(left, right):
    return left + right if type(left) is int and type(right) is int else Bottom("invalid")


def sub(left, right):
    return left - right if type(left) is int and type(right) is int else Bottom("invalid")


def eq(left, right):
    return boolean(left == right)


def lt(left, right):
    return boolean(left < right) if type(left) is int and type(right) is int else Bottom("invalid")


def le(left, right):
    return boolean(left <= right) if type(left) is int and type(right) is int else Bottom("invalid")


def list_lex_lt(left, right):
    if type(left) is not tuple or type(right) is not tuple:
        return Bottom("invalid")
    return boolean(left < right)


_ORIGINAL_HOSTS = {}


def _guard_cards(name):
    @wraps(_ORIGINAL_HOSTS[name])
    def checked(*args):
        return _ORIGINAL_HOSTS[name](*args) if all(valid_cards(arg) for arg in args) else Bottom("invalid")
    return checked


for _name in ("note_shift", "transpose", "slice_events", "concat", "events", "beats", "score_view",
              "list_length", "list_get", "list_slice", "list_cons", "list_append", "list_unique",
              "list_contains", "pair", "first", "second", "add", "sub", "eq", "lt", "le",
              "list_lex_lt"):
    _ORIGINAL_HOSTS[_name] = globals()[_name]
    globals()[_name] = _guard_cards(_name)
