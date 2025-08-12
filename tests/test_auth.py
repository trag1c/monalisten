from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import TYPE_CHECKING

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

    client = Monalisten(url, log_auth_warnings=True)
    hooks_triggered = 0

    @client.on("*")
    async def _(_: types.WebhookEvent) -> None:
        nonlocal hooks_triggered
        hooks_triggered += 1

    with pytest.warns(
        UserWarning, match=f"Received {SIG_HEADER} header, but no token was set"
    ):
        await client.listen()

    assert hooks_triggered == 2


@pytest.mark.parametrize(
    ("sig_header_entry", "warn_check", "should_be_triggered"),
    [
        ({}, pytest.warns(match=f"Missing {SIG_HEADER} header"), False),
        (
            {SIG_HEADER: sign_auth_event("wrong")},
            pytest.warns(match=f"{SIG_HEADER} header does not match set token"),
            False,
        ),
        ({SIG_HEADER: sign_auth_event("foobar")}, nullcontext(), True),
    ],
)
@pytest.mark.asyncio
async def test_validation(
    sse_server: tuple[ServerQueue, str],
    sig_header_entry: dict[str, str],
    warn_check: AbstractContextManager,
    should_be_triggered: bool,
) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_AUTH_EVENT | sig_header_entry)
    await queue.end_signal()

    client = Monalisten(url, token="foobar", log_auth_warnings=True)
    hook_triggered = False

    @client.on("*")
    async def _(_: types.WebhookEvent) -> None:
        nonlocal hook_triggered
        hook_triggered = True

    with warn_check:
        await client.listen()

    assert hook_triggered is should_be_triggered
