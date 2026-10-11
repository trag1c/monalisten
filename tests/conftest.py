from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .redis_server import run_fake_redis
from .sse_server import ServerQueue, run_sse_server

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .redis_server import FakeRedis
    from .server_utils import Server


@pytest.fixture
async def sse_server() -> AsyncIterator[tuple[ServerQueue, str]]:
    async with run_sse_server() as server:
        yield server


@pytest.fixture
async def redis_server() -> AsyncIterator[tuple[FakeRedis, str]]:
    async with run_fake_redis() as server:
        yield server


@pytest.fixture(params=("sse", "redis"))
async def server(request: pytest.FixtureRequest) -> AsyncIterator[tuple[Server, str]]:
    run_server = run_sse_server if request.param == "sse" else run_fake_redis
    async with run_server() as server:
        yield server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
