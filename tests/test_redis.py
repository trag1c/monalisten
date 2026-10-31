from __future__ import annotations

import asyncio
import time
from contextlib import aclosing
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import pytest
import redis
from redis import asyncio as aioredis

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
        _ = extract_stream_name(urlsplit("redis://localhost:6379"))


def test_extract_stream_name_missing_marker() -> None:
    with pytest.raises(MonalistenSetupError, match="`/stream/<stream-name>`"):
        _ = extract_stream_name(urlsplit("redis://localhost:6379/0/topic/webhooks"))


async def _next_payload(url: str) -> EventPayload:
    async with aclosing(_payloads(url)) as agen:
        return await anext(agen)


async def test_starts_from_latest_entry(redis_server: tuple[FakeRedis, str]) -> None:
    fake, url = redis_server
    fake.xadd({"body": '{"added": "before the client connected"}'})

    async with aclosing(_payloads(url)) as agen:
        pending = asyncio.create_task(anext(agen))
        _ = await fake.xread_parked.wait()
        fake.xadd({"body": '{"added": "after"}'})
        payload = await pending

    assert payload == {"body": {"added": "after"}}


async def test_payload_body_loading(redis_server: tuple[FakeRedis, str]) -> None:
    fake, url = redis_server

    async with aclosing(_payloads(url)) as agen:
        pending = asyncio.create_task(anext(agen))
        _ = await fake.xread_parked.wait()
        fake.xadd({
            "x-github-event": "push",
            "x-github-delivery": "abc",
            "x-hub-signature-256": "sha256=deadbeef",
            "body": '{"foo": "bar"}',
        })
        fake.xadd({"body": "not json"})
        first = await pending
        second = await anext(agen)  # same XREAD batch

    assert first == {
        "x-github-event": "push",
        "x-github-delivery": "abc",
        "x-hub-signature-256": "sha256=deadbeef",
        "body": {"foo": "bar"},
    }
    assert second == {"body": "not json"}


async def test_server_side_timeouts_dont_delay_events(
    redis_server: tuple[FakeRedis, str],
) -> None:
    fake, url = redis_server

    async with aclosing(_payloads(url)) as agen:
        pending = asyncio.create_task(anext(agen))
        _ = await fake.xread_parked.wait()
        fake.xadd({"body": "{}"})
        payload = await pending

    assert payload == {"body": {}}


async def test_client_side_timeouts_dont_delay_events(
    redis_server: tuple[FakeRedis, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, url = redis_server

    # Simulate the client's socket timing out on an XREAD (redis-py surfaces socket
    # timeouts as `redis.TimeoutError`) instead of racing a tiny `socket_timeout`
    # against the BLOCK XREAD: rapidly cancelling in-flight reads, dropping the
    # transport, and reconnecting wedges the Windows proactor event loop on Python 3.11.
    xreads = 0
    real_xread = aioredis.Redis.xread

    async def timing_out_xread(self: aioredis.Redis, *args: Any, **kwargs: Any) -> Any:
        nonlocal xreads
        xreads += 1
        if xreads < 9:
            msg = "simulated socket timeout"
            raise redis.TimeoutError(msg)
        return await real_xread(self, *args, **kwargs)

    monkeypatch.setattr(aioredis.Redis, "xread", timing_out_xread)

    async def deliver() -> None:
        # the parked XREAD is the first one to actually reach the server
        _ = await fake.xread_parked.wait()
        fake.xadd({"body": "{}"})

    start = time.monotonic()
    payload, _ = await asyncio.gather(_next_payload(url), deliver())
    elapsed = time.monotonic() - start

    assert payload == {"body": {}}
    assert xreads == 9
    assert elapsed < 0.2


async def test_reconnects_on_dropped_connection(
    redis_server: tuple[FakeRedis, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, url = redis_server
    monkeypatch.setattr("monalisten._redis.MAX_RETRY_DELAY_S", 0.01)
    fake.kill_next_xread = True

    async def deliver() -> None:
        # the parked XREAD is the reconnected one; the first was dropped
        _ = await fake.xread_parked.wait()
        fake.xadd({"body": "{}"})

    payload, _ = await asyncio.gather(_next_payload(url), deliver())
    assert payload == {"body": {}}


async def test_resumes_from_last_id_after_disconnect(
    redis_server: tuple[FakeRedis, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, url = redis_server
    monkeypatch.setattr("monalisten._redis.MAX_RETRY_DELAY_S", 0.01)

    async with aclosing(_payloads(url)) as agen:
        pending = asyncio.create_task(anext(agen))
        _ = await fake.xread_parked.wait()
        fake.xadd({"body": '{"n": 1}'})
        first = await pending

        fake.kill_next_xread = True  # the next XREAD is dropped mid-stream
        pending = asyncio.create_task(anext(agen))
        _ = await fake.xread_parked.wait()  # the reconnected XREAD
        fake.xadd({"body": '{"n": 2}'})
        fake.xadd({"body": '{"n": 3}'})
        second = await pending
        third = await anext(agen)  # same XREAD batch

    # entry 1 must not be re-delivered after the reconnect
    assert (first, second, third) == (
        {"body": {"n": 1}},
        {"body": {"n": 2}},
        {"body": {"n": 3}},
    )
