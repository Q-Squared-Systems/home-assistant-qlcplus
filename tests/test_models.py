"""Unit tests for durable Function identity and duplicate handling."""

from custom_components.qlcplus.models import QLCFunction, normalize


def test_normalize_is_case_and_whitespace_insensitive() -> None:
    assert normalize("  House   Red ") == "house red"


def test_function_identity_does_not_contain_numeric_id() -> None:
    old = QLCFunction(12, "House Red", "Scene", False)
    changed_id = QLCFunction(99, "House Red", "Scene", True)
    assert old.identity == changed_id.identity


def test_duplicate_functions_have_deterministic_distinct_identities() -> None:
    first = QLCFunction(1, "Flash", "Scene", False, 1)
    second = QLCFunction(2, "Flash", "Scene", False, 2)
    assert first.identity != second.identity
