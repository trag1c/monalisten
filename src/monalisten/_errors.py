from __future__ import annotations

from enum import Enum
from typing import Any, NamedTuple, TypedDict

EventPayload = TypedDict(
    "EventPayload",
    {
        "body": dict[str, Any],
        # This only lists headers that GitHub considers special; others may be present.
        "x-github-hook-id": str,
        "x-github-event": str,
        "x-github-delivery": str,
        "x-hub-signature": str,
        "x-hub-signature-256": str,
        "user-agent": str,
        "x-github-hook-installation-target-type": str,
        "x-github-hook-installation-target-id": str,
    },
)


class AuthIssueKind(Enum):
    MISSING = "missing"
    """Client has set token, but no signature was received."""
    UNEXPECTED = "unexpected"
    """Client has no set token, but a signature was received."""
    MISMATCH = "mismatch"
    """Client's token couldn't verify received signature."""


class AuthIssue(NamedTuple):
    """An object representing auth issue events reported by the Monalisten client."""

    kind: AuthIssueKind
    payload: EventPayload


class MonalistenPreprocessingError(Exception):
    """Exception for preprocessing errors encountered by the Monalisten client."""


class MonalistenSetupError(Exception):
    """Exception for Monalisten errors occurring before client creation."""


class Error(NamedTuple):
    """An object representing runtime error events reported by the Monalisten client."""

    exc: Exception
    event_name: str | None
    payload: EventPayload | None
