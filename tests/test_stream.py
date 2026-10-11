from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import Monalisten

from .server_utils import listen_until

if TYPE_CHECKING:
    from monalisten import EventPayload

    from .server_utils import Server
    from .sse_server import ServerQueue


async def test_core_streaming(server: tuple[Server, str]) -> None:
    queue, url = server
    await queue.send_event({"body": {"foo": "bar"}})
    await queue.send_event({"body": {"baz": "qux"}})
    await queue.end_signal()

    client = Monalisten(url)
    received_events: list[EventPayload] = []

    async def spoofed_handle_payload(payload: EventPayload) -> None:
        received_events.append(payload)

    client._auth_and_handle_payload = spoofed_handle_payload  # ty:ignore[invalid-assignment]

    await listen_until(client, lambda: len(received_events) == 2)

    assert received_events == [{"body": {"foo": "bar"}}, {"body": {"baz": "qux"}}]


@pytest.mark.parametrize("payload", ["{}", "{ }"])
async def test_ignore_no_data(
    sse_server: tuple[ServerQueue, str], payload: str
) -> None:
    queue, url = sse_server
    await queue.send_raw(payload)
    await queue.end_signal()

    client = Monalisten(url)
    await client.listen()
