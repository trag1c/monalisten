from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, cast

from aiohttp import web

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
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue

    async def send_event(self, data: dict[str, Any]) -> None:
        await self._queue.put(json.dumps(data, separators=(",", ":")))

    async def end_signal(self) -> None:
        await self._queue.put(None)
