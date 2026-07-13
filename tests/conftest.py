"""Shared pytest fixtures for the AROS test suite.

The autouse fixture isolates configuration and the cached database engine
between tests so each test starts from a clean, predictable state.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Generator[None, None, None]:
    import core.database
    from core.config import get_config

    get_config.cache_clear()
    core.database._ENGINE = None
    yield
    get_config.cache_clear()
    core.database._ENGINE = None
