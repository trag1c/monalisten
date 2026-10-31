from __future__ import annotations

import asyncio
import json
from contextlib import aclosing, suppress
from typing import TYPE_CHECKING, cast
from urllib.parse import SplitResult, urlunsplit

import redis
from redis import asyncio as aioredis

from monalisten._errors import MonalistenSetupError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from monalisten._auth import EventPayload

XREAD_BLOCK_MS = 60_000

MAX_RETRY_DELAY_S = 60


def _preprocess_message(message: dict[str, str]) -> EventPayload:
    message_casefolded = {k.casefold(): v for k, v in message.items()}
    payload = {}
    with suppress(KeyError):
        raw = message_casefolded.pop("body")
        try:
            payload["body"] = json.loads(raw)
        except json.JSONDecodeError:
            payload["body"] = raw  # reported by the sanity check
    return cast("EventPayload", payload | message_casefolded)


def extract_stream_name(split: SplitResult) -> tuple[str, str]:
    scheme, netloc, path, query, fragment = split

    # We expect the path to be of the form `.../stream/some-name`
    path_segments = path.rstrip("/").split("/")
    if len(path_segments) < 3:
        msg = "failed to extract the stream name from the Redis URL"
        raise MonalistenSetupError(msg)

    *init, marker, stream_name = path_segments
    if marker != "stream":
        msg = "expected the Redis URL to contain `/stream/<stream-name>` in its path"
        raise MonalistenSetupError(msg)
    core_path = "/".join(init)

    return urlunsplit((scheme, netloc, core_path, query, fragment)), stream_name


async def aiter_redis_payloads(url: str, stream: str) -> AsyncIterator[EventPayload]:
    client = aioredis.from_url(
        url,
        decode_responses=True,
        protocol=2,
        socket_timeout=None,
        socket_connect_timeout=5,
    )
    async with aclosing(client):
        last_id = "$"  # the latest message ID currently in the stream
        attempts = 0
        while True:
            try:
                streams = cast(
                    "list[tuple[str, list[tuple[str, dict[str, str]]]]]",
                    await client.xread({stream: last_id}, block=XREAD_BLOCK_MS),
                )
            except redis.TimeoutError:
                attempts = 0
                continue
            except (redis.ResponseError, redis.AuthenticationError) as exc:
                msg = f"redis error: {exc}"
                raise MonalistenSetupError(msg) from exc
            except redis.RedisError:
                await asyncio.sleep(min(2 ** min(attempts, 6), MAX_RETRY_DELAY_S))
                attempts += 1
                continue
            attempts = 0
            for _, messages in streams:
                for message_id, message in messages:
                    last_id = message_id
                    yield _preprocess_message(message)
