from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .sse_server import QUEUE_KEY, ServerQueue, start_test_server

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def sse_server() -> AsyncIterator[tuple[ServerQueue, str]]:
    app, runner, port = await start_test_server()
    yield ServerQueue(app[QUEUE_KEY]), f"http://127.0.0.1:{port}/events"
    await runner.cleanup()
