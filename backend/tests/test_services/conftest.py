"""Local conftest for test_services — overrides the root autouse DB fixture.

Most service-level tests use mocked dependencies and do NOT need a live
PostgreSQL connection.  By re-defining the ``setup_database`` fixture here
with ``autouse=True`` we shadow the root conftest version for every test
collected under tests/test_services/.
"""

import pytest


@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: service unit tests mock their own DB sessions."""
    yield
