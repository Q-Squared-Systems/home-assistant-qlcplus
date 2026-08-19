"""Unit tests for durable Function identity and duplicate handling."""

from custom_components.qlcplus.models import QLCFunction, normalize
from custom_components.qlcplus.switch import _has_active_filter, _is_exposed


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


def test_prefix_filter_limits_exposure() -> None:
    function = QLCFunction(1, "HA_House Red", "Scene", False)

    class Entry:
        options = {"name_prefix": "HA_"}

    assert _has_active_filter(Entry())
    assert _is_exposed(Entry(), function)
