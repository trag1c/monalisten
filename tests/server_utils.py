from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from monalisten import Monalisten


class Server(Protocol):
    async def send_event(self, data: dict[str, Any]) -> None: ...
    async def end_signal(self) -> None: ...


async def listen_until(client: Monalisten, condition: Callable[[], bool]) -> None:
    """Run `client.listen()` until `condition` holds or `listen()` finishes/raises.

    Needed for sources without end-of-stream (Redis), where `listen()` never
    returns on its own; works uniformly for SSE too.
    """
    task = asyncio.create_task(client.listen())
    deadline = asyncio.get_running_loop().time() + 1.0  # arbitrary timeout
    try:
        while not condition():
            if task.done():
                task.result()
                return
            assert asyncio.get_running_loop().time() < deadline, "listen_until: timeout"
            await asyncio.sleep(0.01)
    finally:
        if not task.done():
            _ = task.cancel()
            with suppress(asyncio.CancelledError):
                await task
