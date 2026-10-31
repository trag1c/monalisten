from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from monalisten._auth import EventPayload


class MonalistenPreprocessingError(Exception):
    """Exception for preprocessing errors encountered by the Monalisten client."""


class MonalistenSetupError(Exception):
    """Exception for Monalisten errors occurring before client setup."""


class Error(NamedTuple):
    """An object representing runtime error events reported by the Monalisten client."""

    exc: Exception
    event_name: str | None
    payload: EventPayload | None
