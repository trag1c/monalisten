from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import Monalisten, types
from tests.ghk_utils import DUMMY_AUTH_EVENT, DUMMY_STAR_EVENT

if TYPE_CHECKING:
    from .sse_server import ServerQueue


@pytest.mark.asyncio
async def test_regular_scenario(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.send_event(DUMMY_STAR_EVENT)
    await queue.end_signal()

    hooks_triggered = [False, False]
    client = Monalisten(url)

    @client.on("github_app_authorization")
    async def _(_: types.GithubAppAuthorizationEvent) -> None:
        hooks_triggered[0] = True

    @client.on("star")
    async def _(_: types.StarEvent) -> None:
        hooks_triggered[1] = True

    await client.listen()

    assert all(hooks_triggered)


@pytest.mark.asyncio
async def test_one_event_multiple_hooks(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_STAR_EVENT)
    await queue.end_signal()

    hooks_triggered = [False, False]
    client = Monalisten(url)

    @client.on("star")
    async def _(_: types.StarEvent) -> None:
        hooks_triggered[0] = True

    @client.on("star")
    async def _(_: types.StarEvent) -> None:
        hooks_triggered[1] = True

    await client.listen()

    assert all(hooks_triggered)


@pytest.mark.asyncio
async def test_multiple_events_one_hook(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_STAR_EVENT)
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.end_signal()

    trigger_count = 0
    client = Monalisten(url)

    @client.on("github_app_authorization")
    @client.on("star")
    async def _(_: types.GithubAppAuthorizationEvent) -> None:
        nonlocal trigger_count
        trigger_count += 1

    await client.listen()

    assert trigger_count == 2


@pytest.mark.asyncio
async def test_wildcard_hook(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_STAR_EVENT)
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.end_signal()

    trigger_count = 0
    client = Monalisten(url)

    @client.on("*")
    @client.on("github_app_authorization")
    @client.on("star")
    async def _(_: types.WebhookEvent) -> None:
        nonlocal trigger_count
        trigger_count += 1

    await client.listen()

    assert trigger_count == 4
