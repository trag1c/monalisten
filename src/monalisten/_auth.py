from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from githubkit import webhooks

EventPayload = TypedDict(
    "EventPayload",
    {
        "body": dict[str, Any],
        # These are the only headers needed by Monalisten; others may be present.
        "x-github-event": str,
        "x-hub-signature-256": str,
    },
)

SIG_HEADER = "x-hub-signature-256"


class AuthResult(Enum):
    OK = "ok"
    """Client's token successfully verified received signature."""
    MISSING = "missing"
    """Client has set token, but no signature was received."""
    UNEXPECTED = "unexpected"
    """Client has no set token, but a signature was received."""
    MISMATCH = "mismatch"
    """Client's token couldn't verify received signature."""


def authenticate_payload(payload: EventPayload, token: str | None) -> AuthResult:
    if not token:
        if SIG_HEADER in payload:
            return AuthResult.UNEXPECTED
        return AuthResult.OK

    if not (signature := payload.get(SIG_HEADER)):
        return AuthResult.MISSING

    if webhooks.verify(token, payload["body"], signature):
        return AuthResult.OK

    return AuthResult.MISMATCH
