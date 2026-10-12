from __future__ import annotations

import asyncio
import time
from contextlib import aclosing
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import pytest

from monalisten import MonalistenSetupError
from monalisten._redis import aiter_redis_payloads, extract_stream_name

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from monalisten import EventPayload

    from .redis_server import FakeRedis


def _payloads(url: str) -> AsyncGenerator[EventPayload, None]:
    # aiter_redis_payloads is declared as returning AsyncIterator; the tests
    # need the concrete async generator for anext()/aclose() typing.
    return cast("AsyncGenerator[EventPayload, None]", aiter_redis_payloads(url, "test"))


def test_extract_stream_name() -> None:
    url, stream = extract_stream_name(
        urlsplit("redis://user:pass@localhost:6379/0/stream/webhooks?socket_timeout=5")
    )
    assert url == "redis://user:pass@localhost:6379/0?socket_timeout=5"
    assert stream == "webhooks"


def test_extract_stream_name_missing_segments() -> None:
    with pytest.raises(MonalistenSetupError, match="failed to extract"):
        extract_stream_name(urlsplit("redis://localhost:6379"))


def test_extract_stream_name_missing_marker() -> None:
    with pytest.raises(MonalistenSetupError, match="`/stream/<stream-name>`"):
        extract_stream_name(urlsplit("redis://localhost:6379/0/topic/webhooks"))


async def _next_payload(url: str) -> EventPayload:
    async with aclosing(_payloads(url)) as agen:
        return await anext(agen)


async def test_payload_body_loading(redis_server: tuple[FakeRedis, str]) -> None:
    fake, url = redis_server
    fake.xadd({
        "x-github-event": "push",
        "x-github-delivery": "abc",
        "x-hub-signature-256": "sha256=deadbeef",
        "body": '{"foo": "bar"}',
    })
    fake.xadd({"body": "not json"})

    async with aclosing(_payloads(url)) as agen:
        first = await anext(agen)
        second = await anext(agen)

    assert first == {
        "x-github-event": "push",
        "x-github-delivery": "abc",
        "x-hub-signature-256": "sha256=deadbeef",
        "body": {"foo": "bar"},
    }
    assert second == {}


async def test_server_side_timeouts_dont_delay_events(
    redis_server: tuple[FakeRedis, str],
) -> None:
    fake, url = redis_server

    async with aclosing(_payloads(url)) as agen:
        pending = asyncio.create_task(anext(agen))
        fake.xadd({"body": "{}"})
        payload = await pending

    assert payload == {"body": {}}


async def test_client_side_timeouts_dont_delay_events(
    redis_server: tuple[FakeRedis, str],
) -> None:
    fake, url = redis_server
    fake.xadd({"body": "{}"})
    fake.release_on = 9  # hide the entry until the 9th XREAD

    start = time.monotonic()
    payload = await _next_payload(f"{url}?socket_timeout=0.01")
    elapsed = time.monotonic() - start

    assert payload == {"body": {}}
    assert elapsed < 0.2


async def test_reconnects_on_dropped_connection(
    redis_server: tuple[FakeRedis, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, url = redis_server
    monkeypatch.setattr("monalisten._redis.MAX_RETRY_DELAY_S", 0.01)
    fake.kill_next_xread = True
    fake.xadd({"body": "{}"})

    assert await _next_payload(url) == {"body": {}}
