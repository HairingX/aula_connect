"""What every test shares."""

from collections.abc import Iterator
from datetime import timedelta

import pytest

from aula_connect import read_marks


@pytest.fixture(autouse=True)
def no_wait_to_read_marks_again() -> Iterator[None]:
    """Read the marks of what the user has seen again at once, not seconds later."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(read_marks, "RECHECK_AFTER", timedelta(0))
        yield
