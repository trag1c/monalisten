from __future__ import annotations

import asyncio
import math
from itertools import count
from typing import TYPE_CHECKING, cast

import httpx
from httpx_sse import ServerSentEvent, aconnect_sse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from monalisten._auth import EventPayload


async def _aiter_sse_retrying(
    client: httpx.AsyncClient, method: str, url: str
) -> AsyncIterator[ServerSentEvent]:
    last_event_id: str | None = None
    retry_delay = 0.0
    for attempt in count():
        try:
            headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
            async with aconnect_sse(client, method, url, headers=headers) as stream:
                async for sse in stream.aiter_sse():
                    last_event_id = sse.id
                    retry_delay = (sse.retry or 0) / 1000
                    yield sse
                break
        except httpx.ReadError:
            await asyncio.sleep(retry_delay + 2 ** (min(attempt, 10) / math.e))


async def aiter_sse_payloads(url: str) -> AsyncIterator[EventPayload]:
    async with httpx.AsyncClient(timeout=None) as client:
        async for event in _aiter_sse_retrying(client, "GET", url):
            if payload := {k.casefold(): v for k, v in event.json().items()}:
                yield cast("EventPayload", payload)
