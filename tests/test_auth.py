from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import AuthResult, Monalisten
from monalisten._auth import SIG_HEADER
from monalisten._core import EVENT_HEADER

from .ghk_utils import DUMMY_AUTH_EVENT, sign_auth_event
from .server_utils import Server, listen_until

if TYPE_CHECKING:
    from monalisten import Error, EventPayload, events


async def test_no_token(server: tuple[Server, str]) -> None:
    queue, url = server
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.send_event(DUMMY_AUTH_EVENT | {SIG_HEADER: "sha256=0"})
    await queue.end_signal()

    client = Monalisten(url)
    hooks_triggered = 0
    received_results: list[AuthResult] = []

    @client.event.any
    async def _(_: events.Any) -> None:
        nonlocal hooks_triggered
        hooks_triggered += 1

    @client.internal.auth_issue
    async def _(_: EventPayload, result: AuthResult) -> None:
        received_results.append(result)

    await listen_until(client, lambda: hooks_triggered == 2)

    assert hooks_triggered == 2
    assert received_results == [AuthResult.UNEXPECTED]


@pytest.mark.parametrize(
    ("sig_header_entry", "expected_issues", "should_be_triggered"),
    [
        ({}, [AuthResult.MISSING], False),
        ({SIG_HEADER: sign_auth_event("wrong")}, [AuthResult.MISMATCH], False),
        ({SIG_HEADER: sign_auth_event("foobar")}, [], True),
        ({SIG_HEADER.title(): sign_auth_event("foobar")}, [], True),
    ],
)
async def test_validation(
    server: tuple[Server, str],
    sig_header_entry: dict[str, str],
    expected_issues: list[AuthResult],
    should_be_triggered: bool,
) -> None:
    queue, url = server
    await queue.send_event(DUMMY_AUTH_EVENT | sig_header_entry)
    await queue.end_signal()

    client = Monalisten(url, token="foobar")
    hook_triggered = False
    received_issues: list[AuthResult] = []

    @client.event.any
    async def _(_: events.Any) -> None:
        nonlocal hook_triggered
        hook_triggered = True

    @client.internal.auth_issue
    async def _(_: EventPayload, result: AuthResult) -> None:
        received_issues.append(result)

    await listen_until(client, lambda: hook_triggered or bool(received_issues))

    assert hook_triggered is should_be_triggered
    assert received_issues == expected_issues


# Covers a prior case where a payload with `x-github-event` and `x-hub-signature-256`
# headers but no `body` would crash the authentication check if a token was set.
async def test_no_eager_body_access(server: tuple[Server, str]) -> None:
    queue, url = server
    await queue.send_event({SIG_HEADER: "foo", EVENT_HEADER: "bar"})
    await queue.end_signal()

    client = Monalisten(url, token="foo")
    error_captured = False

    @client.internal.error
    async def _(_: Error) -> None:
        nonlocal error_captured
        error_captured = True

    await listen_until(client, lambda: error_captured)

    assert error_captured
