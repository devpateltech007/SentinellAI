"""Smoke test: the package imports and has a version."""

import compliancelens


def test_version_is_set():
    assert isinstance(compliancelens.__version__, str)
    assert compliancelens.__version__
