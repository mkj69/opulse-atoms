"""Check that retained localized scripts differ only by approved ASCII aliases."""

from pathlib import Path

LEGACY_ASCII_CHANGES = {
    "challenge.js": {"←": "<-", "→": "->"},
    "challenge-modes.js": {"←": "<-", "→": "->"},
    "granularity.js": {" ×": " x"},
    "granularity-anim.js": {"1×": "1x", '"½"': '"0.5"', '"×"': '"x"'},
    "scales-core.js": {"–": "-", "→": "->"},
    "scales-growth.js": {"≈": "about ", "→": "->"},
    "scales-solve.js": {"≈": "about ", "→": "->"},
    "scales-tour.js": {"≈": "about ", "→": "->"},
}


def assert_ascii_legacy_mirror(source: Path, mirror: Path) -> None:
    actual = source.read_text(encoding="utf-8")
    expected = mirror.read_text(encoding="utf-8")
    if actual == expected:
        return
    for old, new in LEGACY_ASCII_CHANGES.get(source.name, {}).items():
        assert old in expected, (mirror, old)
        expected = expected.replace(old, new)
    assert actual == expected
