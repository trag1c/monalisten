from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import Monalisten

if TYPE_CHECKING:
    from httpx_sse import ServerSentEvent

    from .sse_server import ServerQueue


@pytest.mark.asyncio
async def test_core_streaming(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event({})
    await queue.send_event({"foo": "bar"})
    await queue.end_signal()

    client = Monalisten(url)
    received_events: list[ServerSentEvent] = []

    async def spoofed_handle_event(event: ServerSentEvent) -> None:
        received_events.append(event)

    client._handle_event = spoofed_handle_event

    await client.listen()

    assert len(received_events) == 2
    assert all(e.event == "message" for e in received_events)
    assert received_events[0].data == "{}"
    assert received_events[1].data == '{"foo":"bar"}'


@pytest.mark.parametrize("payload", ["{}", "{ }"])
@pytest.mark.asyncio
async def test_ignore_no_data(
    sse_server: tuple[ServerQueue, str], payload: str
) -> None:
    queue, url = sse_server
    await queue._queue.put(payload)
    await queue.end_signal()

    client = Monalisten(url)
    await client.listen()
