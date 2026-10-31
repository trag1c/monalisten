from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from monalisten import AuthResult, Monalisten
from monalisten._auth import SIG_HEADER
from tests.ghk_utils import DUMMY_AUTH_EVENT, DUMMY_STAR_EVENT, sign_auth_event

if TYPE_CHECKING:
    from monalisten import EventPayload, events


async def test_regular_scenario() -> None:

    hooks_triggered = [False, False]
    client = Monalisten("bobr://bob.er/")

    @client.event.github_app_authorization
    async def _(_: events.GithubAppAuthorization) -> None:
        hooks_triggered[0] = True

    @client.event.star
    async def _(_: events.Star) -> None:
        hooks_triggered[1] = True

    for event in (DUMMY_AUTH_EVENT, DUMMY_STAR_EVENT):
        await client.dispatch_event(
            cast("str", event["X-GitHub-Event"]), cast("dict[str, Any]", event["body"])
        )

    assert all(hooks_triggered)


@pytest.mark.parametrize(
    ("token", "headers", "expected_kind"),
    [
        (None, {SIG_HEADER: "sha256=0"}, AuthResult.UNEXPECTED),
        ("foobar", {SIG_HEADER: sign_auth_event("foobaz")}, AuthResult.MISMATCH),
        ("foobar", {SIG_HEADER: None}, AuthResult.MISSING),
    ],
)
async def test_auth(
    token: str | None, headers: dict[str, Any], expected_kind: AuthResult
) -> None:

    client = Monalisten("bobr://bob.er/", token=token)

    @client.internal.auth_issue
    async def _(_: EventPayload, result: AuthResult) -> None:
        raise PermissionError(result)

    with pytest.raises(PermissionError, check=lambda exc: exc.args[0] is expected_kind):
        await client.dispatch_event("star", {"action": "created"}, headers=headers)
