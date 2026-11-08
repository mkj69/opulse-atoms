"""Session-scoped verified kitchen library shared across kitchen tests."""

import pytest

from opulse.worlds_v2.kitchen.depth_story import build_library


@pytest.fixture(scope="session")
def library():
    return build_library()
