"""Domain models independent of Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
import re


def normalize(value: str) -> str:
    """Return a stable, case-insensitive key component."""
    return re.sub(r"\s+", " ", value.strip()).casefold()


@dataclass(frozen=True, slots=True)
class QLCFunction:
    """A QLC+ Function discovered from the Web API."""

    function_id: int
    name: str
    function_type: str
    running: bool
    occurrence: int = 1

    @property
    def identity(self) -> str:
        """Stable fallback identity; QLC+ does not expose a function UUID."""
        return f"{normalize(self.function_type)}:{normalize(self.name)}:{self.occurrence}"

    @property
    def selector_key(self) -> str:
        """Human-readable, unambiguous option selector."""
        return f"{self.function_type}: {self.name} [{self.occurrence}]"
