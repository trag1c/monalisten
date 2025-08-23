from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from monalisten import Monalisten, types
from monalisten._core import SIG_HEADER

from .ghk_utils import DUMMY_AUTH_EVENT, sign_auth_event

if TYPE_CHECKING:
    from .sse_server import ServerQueue


@pytest.mark.asyncio
async def test_no_token(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.send_event(DUMMY_AUTH_EVENT | {SIG_HEADER: "sha256=0"})
    await queue.end_signal()

    client = Monalisten(url)
    hooks_triggered = 0
    received_issues: list[str] = []

    @client.on("*")
    async def _(_: types.WebhookEvent) -> None:
        nonlocal hooks_triggered
        hooks_triggered += 1

    @client.on_internal("auth_issue")
    async def _(_: dict[str, Any], message: str) -> None:
        received_issues.append(message)

    await client.listen()

    assert hooks_triggered == 2
    assert received_issues == [f"Received {SIG_HEADER} header, but no token was set"]


@pytest.mark.parametrize(
    ("sig_header_entry", "expected_issues", "should_be_triggered"),
    [
        ({}, [f"Missing {SIG_HEADER} header"], False),
        (
            {SIG_HEADER: sign_auth_event("wrong")},
            [f"{SIG_HEADER} header does not match set token"],
            False,
        ),
        ({SIG_HEADER: sign_auth_event("foobar")}, [], True),
        ({SIG_HEADER.title(): sign_auth_event("foobar")}, [], True),
    ],
)
@pytest.mark.asyncio
async def test_validation(
    sse_server: tuple[ServerQueue, str],
    sig_header_entry: dict[str, str],
    expected_issues: list[str],
    should_be_triggered: bool,
) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_AUTH_EVENT | sig_header_entry)
    await queue.end_signal()

    client = Monalisten(url, token="foobar")
    hook_triggered = False
    received_issues: list[str] = []

    @client.on("*")
    async def _(_: types.WebhookEvent) -> None:
        nonlocal hook_triggered
        hook_triggered = True

    @client.on_internal("auth_issue")
    async def _(_: dict[str, Any], message: str) -> None:
        received_issues.append(message)

    await client.listen()

    assert hook_triggered is should_be_triggered
    assert received_issues == expected_issues
