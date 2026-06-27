from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import Monalisten

if TYPE_CHECKING:
    from monalisten._errors import EventPayload

    from .sse_server import ServerQueue


async def test_core_streaming(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event({"foo": "bar"})
    await queue.send_event({})
    await queue.send_event({"baz": "qux"})
    await queue.end_signal()

    client = Monalisten(url)
    received_events: list[EventPayload] = []

    async def spoofed_handle_payload(
        payload: EventPayload, *, skip_auth: bool = False
    ) -> None:
        _ = skip_auth
        received_events.append(payload)

    client._handle_payload = spoofed_handle_payload  # ty:ignore[invalid-assignment]

    await client.listen()

    assert len(received_events) == 2
    assert received_events[0] == {"foo": "bar"}
    assert received_events[1] == {"baz": "qux"}


@pytest.mark.parametrize("payload", ["{}", "{ }"])
async def test_ignore_no_data(
    sse_server: tuple[ServerQueue, str], payload: str
) -> None:
    queue, url = sse_server
    await queue._queue.put(payload)
    await queue.end_signal()

    client = Monalisten(url)
    await client.listen()
