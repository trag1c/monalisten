from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import AuthIssue, AuthIssueKind, Monalisten, events
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
    received_issues: list[AuthIssueKind] = []

    @client.event.any
    async def _(_: events.Any) -> None:
        nonlocal hooks_triggered
        hooks_triggered += 1

    @client.internal.auth_issue
    async def _(issue: AuthIssue) -> None:
        received_issues.append(issue.kind)

    await client.listen()

    assert hooks_triggered == 2
    assert received_issues == [AuthIssueKind.UNEXPECTED]


@pytest.mark.parametrize(
    ("sig_header_entry", "expected_issues", "should_be_triggered"),
    [
        ({}, [AuthIssueKind.MISSING], False),
        ({SIG_HEADER: sign_auth_event("wrong")}, [AuthIssueKind.MISMATCH], False),
        ({SIG_HEADER: sign_auth_event("foobar")}, [], True),
        ({SIG_HEADER.title(): sign_auth_event("foobar")}, [], True),
    ],
)
@pytest.mark.asyncio
async def test_validation(
    sse_server: tuple[ServerQueue, str],
    sig_header_entry: dict[str, str],
    expected_issues: list[AuthIssueKind],
    should_be_triggered: bool,
) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_AUTH_EVENT | sig_header_entry)
    await queue.end_signal()

    client = Monalisten(url, token="foobar")
    hook_triggered = False
    received_issues: list[AuthIssueKind] = []

    @client.event.any
    async def _(_: events.Any) -> None:
        nonlocal hook_triggered
        hook_triggered = True

    @client.internal.auth_issue
    async def _(issue: AuthIssue) -> None:
        received_issues.append(issue.kind)

    await client.listen()

    assert hook_triggered is should_be_triggered
    assert received_issues == expected_issues
