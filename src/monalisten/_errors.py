from enum import Enum
from typing import Any, NamedTuple


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
    event_data: dict[str, Any]


class MonalistenPreprocessingError(Exception):
    """Exception for preprocessing errors encountered by the Monalisten client."""


class MonalistenSetupError(Exception):
    """Exception for Monalisten errors occurring before client creation."""


class Error(NamedTuple):
    """An object representing runtime error events reported by the Monalisten client."""

    exc: Exception
    event_data: dict[str, Any]
