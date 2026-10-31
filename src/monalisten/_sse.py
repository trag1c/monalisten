from __future__ import annotations

import asyncio
import math
from itertools import count
from typing import TYPE_CHECKING, Any, cast

import httpx2

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from monalisten._auth import EventPayload


async def _aiter_sse_retrying(
    client: httpx2.AsyncClient, method: str, url: str
) -> AsyncIterator[httpx2.ServerSentEvent]:
    last_event_id: str | None = None
    retry_delay = 0.0
    for attempt in count():
        try:
            headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
            async with client.sse(url, method=method, headers=headers) as source:
                async for event in source:
                    last_event_id = event.id
                    retry_delay = (event.retry or 0) / 1000
                    yield event
                break
        except httpx2.ReadError:
            await asyncio.sleep(retry_delay + 2 ** (min(attempt, 10) / math.e))


async def aiter_sse_payloads(url: str) -> AsyncIterator[EventPayload]:
    async with httpx2.AsyncClient(timeout=None) as client:
        async for event in _aiter_sse_retrying(client, "GET", url):
            data = cast("dict[str, Any]", event.json())
            if payload := {k.casefold(): v for k, v in data.items()}:
                yield cast("EventPayload", payload)
