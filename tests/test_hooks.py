from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest

from monalisten import Monalisten, events
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

    @client.event.github_app_authorization
    async def _(_: events.GithubAppAuthorization) -> None:
        hooks_triggered[0] = True

    @client.event.star
    async def _(_: events.Star) -> None:
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

    @client.event.star
    async def _(_: events.Star) -> None:
        hooks_triggered[0] = True

    @client.event.star
    async def _(_: events.Star) -> None:
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

    @client.event.github_app_authorization  # pyright: ignore[reportArgumentType]
    @client.event.star
    async def _(_: events.Star | events.GithubAppAuthorization) -> None:
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

    @client.event.any  # pyright: ignore[reportArgumentType]
    @client.event.github_app_authorization  # pyright: ignore[reportArgumentType]
    @client.event.star
    async def _(_: events.Any) -> None:
        nonlocal trigger_count
        trigger_count += 1

    await client.listen()

    assert trigger_count == 4


@pytest.mark.asyncio
async def test_subhooks(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    dummy_star_delete_event = copy.deepcopy(DUMMY_STAR_EVENT)
    dummy_star_delete_event["body"] |= {"action": "deleted", "starred_at": None}
    await queue.send_event(DUMMY_STAR_EVENT)
    await queue.send_event(dummy_star_delete_event)
    await queue.end_signal()

    event_sum = 0
    client = Monalisten(url)

    @client.event.any
    async def _(_: events.Any) -> None:
        nonlocal event_sum
        event_sum += 1

    @client.event.star
    async def _(_: events.Star) -> None:
        nonlocal event_sum
        event_sum += 10

    @client.event.star.created
    async def _(_: events.StarCreated) -> None:
        nonlocal event_sum
        event_sum += 100

    @client.event.star.deleted
    async def _(_: events.StarDeleted) -> None:
        nonlocal event_sum
        event_sum += 1000

    await client.listen()

    assert event_sum == 1122
