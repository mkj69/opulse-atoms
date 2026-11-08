"""Stable dependency order for a batch of jointly saved definitions."""


def dependency_order(definitions):
    """Return indices with saved prerequisites before their consumers."""
    names = {definition.name for definition in definitions if definition is not None}
    pending = set(range(len(definitions)))
    completed = set()
    ordered = []
    while pending:
        ready = next((index for index in sorted(pending)
                      if definitions[index] is None or not (
                          (set(definitions[index].depends_on) & (names - {definitions[index].name}))
                          - completed)), None)
        if ready is None:
            ordered.extend(sorted(pending))
            break
        ordered.append(ready)
        pending.remove(ready)
        if definitions[ready] is not None:
            completed.add(definitions[ready].name)
    return ordered
