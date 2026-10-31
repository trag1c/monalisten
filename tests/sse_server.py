from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, cast

from aiohttp import web

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

QUEUE_KEY = web.AppKey("queue", asyncio.Queue)


async def sse_handler(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await resp.prepare(request)

    queue = request.app[QUEUE_KEY]
    with suppress(asyncio.CancelledError):
        while True:
            if (msg := await queue.get()) is None:
                break
            data = f"data: {msg}\n\n"
            await resp.write(data.encode())
    return resp


async def start_test_server() -> tuple[web.Application, web.AppRunner, int]:
    app = web.Application()
    app[QUEUE_KEY] = asyncio.Queue()
    app.router.add_get("/events", sse_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    _, port = cast("asyncio.Server", site._server).sockets[0].getsockname()
    return app, runner, port


class ServerQueue:
    def __init__(self, queue: asyncio.Queue[str | None]) -> None:
        self._queue = queue

    async def send_event(self, data: dict[str, Any]) -> None:
        await self.send_raw(json.dumps(data, separators=(",", ":")))

    async def send_raw(self, raw_data: str) -> None:
        await self._queue.put(raw_data)

    async def end_signal(self) -> None:
        await self._queue.put(None)


@asynccontextmanager
async def run_sse_server() -> AsyncIterator[tuple[ServerQueue, str]]:
    app, runner, port = await start_test_server()
    try:
        yield ServerQueue(app[QUEUE_KEY]), f"http://127.0.0.1:{port}/events"
    finally:
        await runner.cleanup()
