"""Regression test: CodeResolver must find id2codes_dict.json without explicit path."""
import pytest
from lib.code_resolver import CodeResolver


def test_code_resolver_loads_without_explicit_path():
    """CodeResolver() should not raise FileNotFoundError when dict exists on disk."""
    resolver = CodeResolver()
    assert len(resolver._index) > 0


def test_resolve_sex_male():
    resolver = CodeResolver()
    code_id, confidence, method = resolver.resolve("Male", "Patient.sex")
    assert code_id is not None
    assert confidence > 0.0


def test_resolve_unknown_variable_returns_unresolved():
    resolver = CodeResolver()
    code_id, confidence, method = resolver.resolve("something", "Unknown.field")
    assert code_id is None
    assert method == "unresolved"
