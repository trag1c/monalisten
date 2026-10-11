from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

NIL = b"*-1\r\n"
UNKNOWN = b"-ERR unknown command\r\n"


class FakeRedis:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.new_entry = asyncio.Event()
        self.tasks: set[asyncio.Task[None]] = set()
        self.xread_count = 0
        self.release_on: int | None = None  # hide queued entries until the Nth XREAD
        self.kill_next_xread = False  # close the connection once the next XREAD arrives
        self._counter = 0

    def xadd(self, fields: dict[str, str]) -> None:
        self._counter += 1
        self.entries.append((f"{self._counter}-0", fields))
        self.new_entry.set()

    def entries_after(self, last_id: str) -> list[tuple[str, dict[str, str]]]:
        if last_id == "$":
            return list(self.entries)
        counter = int(last_id.partition("-")[0])
        return [
            entry for entry in self.entries if int(entry[0].partition("-")[0]) > counter
        ]

    async def send_event(self, data: dict[str, Any]) -> None:
        fields: dict[str, str] = {}
        for key, value in data.items():
            # casefolded to match the SSE provider's behavior
            if key.casefold() == "body":
                fields["body"] = json.dumps(value, separators=(",", ":"))
            else:
                fields[key.casefold()] = str(value)
        self.xadd(fields)

    async def end_signal(self) -> None:
        pass  # Redis streams have no end-of-stream, see `utils.listen_until`.


async def _read_command(reader: asyncio.StreamReader) -> list[str]:
    # redis-py only ever sends RESP arrays of bulk strings
    if not (line := await reader.readline()):
        raise EOFError
    parts: list[str] = []
    for _ in range(int(line[1:])):
        _ = await reader.readline()  # $<length>
        parts.append((await reader.readline()).rstrip(b"\r\n").decode())
    return parts


def _bulk(value: str) -> bytes:
    data = value.encode()
    return b"$" + str(len(data)).encode() + b"\r\n" + data + b"\r\n"


def _xread_reply(stream: str, entries: list[tuple[str, dict[str, str]]]) -> bytes:
    reply = (
        b"*1\r\n*2\r\n" + _bulk(stream) + b"*" + str(len(entries)).encode() + b"\r\n"
    )
    for entry_id, fields in entries:
        flat = [part for pair in fields.items() for part in pair]
        reply += b"*2\r\n" + _bulk(entry_id)
        reply += b"*" + str(len(flat)).encode() + b"\r\n" + b"".join(map(_bulk, flat))
    return reply


async def _xread(fake: FakeRedis, cmd: list[str]) -> bytes | None:
    fake.xread_count += 1
    if fake.kill_next_xread:
        fake.kill_next_xread = False
        return None  # close the connection without a reply

    upper = [part.upper() for part in cmd]
    block_s = float(cmd[upper.index("BLOCK") + 1]) / 1000 if "BLOCK" in upper else None
    *_, stream, last_id = cmd

    while True:
        fake.new_entry.clear()
        released = fake.release_on is None or fake.xread_count >= fake.release_on
        if released and (visible := fake.entries_after(last_id)):
            return _xread_reply(stream, visible)
        if block_s is None:
            return NIL
        try:
            _ = await asyncio.wait_for(fake.new_entry.wait(), timeout=block_s)
        except asyncio.TimeoutError:
            return NIL


async def _handle(
    fake: FakeRedis, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        while True:
            cmd = await _read_command(reader)
            if cmd[0].upper() == "XREAD":
                if (reply := await _xread(fake, cmd)) is None:
                    return
            else:
                # The only other command redis-py sends here is CLIENT SETINFO on
                # connect, which is fire-and-forget and tolerates errors.
                reply = UNKNOWN
            writer.write(reply)
            await writer.drain()
    except (EOFError, ConnectionError, asyncio.IncompleteReadError, ValueError):
        pass
    finally:
        writer.close()
        with suppress(ConnectionError, RuntimeError):
            await writer.wait_closed()


@asynccontextmanager
async def run_fake_redis() -> AsyncIterator[tuple[FakeRedis, str]]:
    redis = FakeRedis()

    def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(_handle(redis, reader, writer))
        redis.tasks.add(task)
        task.add_done_callback(redis.tasks.discard)

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    assert server.sockets is not None
    try:
        url = f"redis://127.0.0.1:{server.sockets[0].getsockname()[1]}/0/stream/test"
        yield redis, url
    finally:
        # Cancel the connection handlers *before* `wait_closed()`: a handler parked
        # inside a BLOCK XREAD (up to XREAD_BLOCK_MS) cannot see the client's EOF, and
        # on Python 3.12+ `wait_closed()` waits for such handlers.
        for task in list(redis.tasks):
            _ = task.cancel()
        server.close()
        await server.wait_closed()
        _ = await asyncio.gather(*redis.tasks, return_exceptions=True)
