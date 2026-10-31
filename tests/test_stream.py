from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from monalisten import Monalisten, MonalistenSetupError

from .server_utils import listen_until

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from monalisten import EventPayload

    from .server_utils import Server
    from .sse_server import ServerQueue


async def test_unsupported_scheme() -> None:
    fired = False
    client = Monalisten("ftp://example.com")

    @client.internal.ready
    async def _() -> None:
        nonlocal fired
        fired = True

    with pytest.raises(MonalistenSetupError, match="unsupported URL scheme"):
        await client.listen()

    assert not fired


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


@pytest.mark.parametrize("scheme", ["redis", "rediss"])
async def test_redis_scheme_routing(
    scheme: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, str] = {}

    async def fake_aiter(url: str, stream: str) -> AsyncIterator[EventPayload]:
        seen["url"], seen["stream"] = url, stream
        return
        yield  # unreachable on purpose, just there to force an async generator

    monkeypatch.setattr("monalisten._redis.aiter_redis_payloads", fake_aiter)
    await Monalisten(f"{scheme}://example.com:6379/stream/gh").listen()
    assert seen == {"url": f"{scheme}://example.com:6379", "stream": "gh"}


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_sse_scheme_routing(scheme: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    async def fake_aiter(url: str) -> AsyncIterator[EventPayload]:
        seen["url"] = url
        return
        yield  # unreachable on purpose, just there to force an async generator

    monkeypatch.setattr("monalisten._sse.aiter_sse_payloads", fake_aiter)
    await Monalisten(f"{scheme}://example.com/events").listen()
    assert seen == {"url": f"{scheme}://example.com/events"}
