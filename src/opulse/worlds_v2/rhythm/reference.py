"""Independent depth-design oracle loaded from the catalogue source."""

import importlib.util
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.values import Bottom, Card


@lru_cache(maxsize=1)
def design():
    path = Path(__file__).resolve().parents[4] / 'worlds/catalogue/depth/rhythm.py'
    spec = importlib.util.spec_from_file_location('rhythm_depth_reference', path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def to_reference(value):
    module = design()
    if isinstance(value, Card) and value.sort in ('rhythm', 'accented', 'cycle'):
        from .hosts import cells
        return {'rhythm': module.Rhythm, 'accented': module.Accented,
                'cycle': module.Cycle}[value.sort](cells(value))
    if isinstance(value, tuple):
        return tuple(map(to_reference, value))
    return value


def to_kernel(value):
    module = design()
    if isinstance(value, (module.Rhythm, module.Accented, module.Cycle)):
        from .hosts import to_card
        sort = type(value).__name__.lower()
        return (Card(sort, 'val', (to_card(value.cells),)) if sort != 'rhythm'
                else to_card(value.cells))
    if isinstance(value, tuple):
        return tuple(map(to_kernel, value))
    return value


def evaluate(name, args):
    module = design()
    values = tuple(arg if isinstance(arg, kernel.FnRef) else to_reference(arg) for arg in args)
    if name in ('best_fit', 'phase_count'):
        return getattr(module, name)(*values[0])
    if name in ('stack', 'weave', 'orbit'):
        def function(slot):
            if slot.name == 'identity':
                return module.identity
            return getattr(module, slot.name)
        if name == 'orbit':
            return to_kernel(module.orbit(function(values[0]), values[1]))
        if name == 'weave':
            return to_kernel(module.weave(values[2], values[3], function(values[0]), function(values[1])))
        return to_kernel(module.stack(function(values[0]), function(values[1]), values[2]))
    if name in ('accented', 'accented.make'):
        return to_kernel(module.Accented(values[0].cells)) if 2 in values[0].cells else Bottom('no_accent')
    if name in ('cycle', 'cycle.make'):
        return to_kernel(module.cycle(values[0]))
    if name == 'start_heavy':
        return to_kernel(module.start_heavy(values[0])) if 2 in values[0].cells else Bottom('no_accent')
    if name == 'phase_score':
        if not 0 <= values[2] < len(values[1].cells):
            return Bottom('range')
        return module.phase_score(*values)
    if name == 'silence_weak':
        return to_kernel(module.silence_weak(*values))
    if name == 'infer_phase':
        if not 0 <= values[3] <= 512 or len(values[1].cells) > 32 or len(values[2].cells) > 32:
            return Bottom('range')
        return to_kernel(module.infer_phase(*values))
    return to_kernel(getattr(module, name)(*values))
