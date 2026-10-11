from __future__ import annotations

import asyncio
from importlib.util import find_spec
from itertools import chain
from typing import TYPE_CHECKING, Any, cast, final
from urllib.parse import urlsplit

from githubkit import webhooks
from pydantic import ValidationError

from monalisten._auth import SIG_HEADER, AuthResult, authenticate_payload
from monalisten._errors import Error, MonalistenPreprocessingError, MonalistenSetupError
from monalisten._event_namespace import EventNamespace
from monalisten._namespace import InternalNamespace

if TYPE_CHECKING:
    from collections.abc import Iterable

    from typing_extensions import ParamSpec

    from monalisten._auth import EventPayload
    from monalisten._namespace import Hook

    P = ParamSpec("P")

EVENT_HEADER = "x-github-event"


def _require_extra(*, module: str, extra: str) -> None:
    if find_spec(module) is not None:
        return
    msg = (
        f"the `{module}` module is required for streaming from the set source; "
        f"install the `{extra}` extra"
    )
    raise MonalistenSetupError(msg)


@final
class Monalisten:
    """
    A Monalisten client streaming events from source (`url`),
    optionally secured by the secret `token`.
    """

    def __init__(self, url: str, *, token: str | None = None) -> None:
        self._url = url
        self._token = token
        self._event = EventNamespace()
        self._internal = InternalNamespace()

    @property
    def event(self) -> EventNamespace:
        return self._event

    @property
    def internal(self) -> InternalNamespace:
        return self._internal

    @property
    def url(self) -> str:
        return self._url

    @property
    def token(self) -> str | None:
        return self._token

    async def _raise(
        self,
        exc: Exception,
        payload: EventPayload | None = None,
        event_name: str | None = None,
    ) -> None:
        if payload:
            event_name = event_name or payload.get(EVENT_HEADER)
        if not (error_hooks := self.internal["error"]):
            raise exc
        await self._dispatch_hooks(
            payload, event_name, error_hooks, Error(exc, event_name, payload)
        )

    async def _sanity_check_payload(self, payload: EventPayload) -> bool:
        if not (event_name := payload.get(EVENT_HEADER)):
            msg = f"received data is missing the {EVENT_HEADER} header"
            await self._raise(MonalistenPreprocessingError(msg), payload)
            return False

        if not ((body := payload.get("body")) and isinstance(body, dict)):
            msg = "received data doesn't contain a valid JSON object body"
            await self._raise(MonalistenPreprocessingError(msg), payload, event_name)
            return False

        return True

    async def _handle_payload(self, payload: EventPayload) -> None:
        # These are safe to access because of the sanity check
        event_name, body = payload[EVENT_HEADER], payload["body"]

        hook_kinds = [self.event.any["*"], self.event[event_name]["*"]]
        if action := body.get("action"):
            hook_kinds.append(self.event[event_name][action])

        if not (hooks := list(chain.from_iterable(hook_kinds))):
            # Don't parse an event if nothing will handle it anyway
            return

        try:
            webhook_event = webhooks.parse_obj(event_name, body)
        except ValidationError as pydantic_exc:
            msg = "the received payload could not be parsed as an event"
            exc = MonalistenPreprocessingError(msg)
            exc.__cause__ = pydantic_exc
            await self._raise(exc, payload, event_name)
            return

        await self._dispatch_hooks(payload, event_name, hooks, webhook_event)

    async def _dispatch_auth_issue(
        self, payload: EventPayload, auth_result: AuthResult
    ) -> None:
        await self._dispatch_hooks(
            payload, "auth_issue", self.internal["auth_issue"], payload, auth_result
        )

    async def listen(self) -> None:
        """Start streaming events from the specified source (the client's `url`)."""
        if (split_result := urlsplit(self._url)).scheme in {"redis", "rediss"}:
            _require_extra(module="redis", extra="redis")
            from monalisten._redis import (  # noqa: PLC0415
                aiter_redis_payloads,
                extract_stream_name,
            )

            url, stream = extract_stream_name(split_result)
            payloads = aiter_redis_payloads(url, stream)
        elif split_result.scheme in {"http", "https"}:
            _require_extra(module="httpx_sse", extra="sse")
            from monalisten._sse import aiter_sse_payloads  # noqa: PLC0415

            payloads = aiter_sse_payloads(self._url)
        else:
            msg = f"unsupported URL scheme `{split_result.scheme}`"
            raise MonalistenSetupError(msg)

        await self._dispatch_hooks(None, "ready", self.internal["ready"])
        async for payload in payloads:
            await self._auth_and_handle_payload(payload)

    async def _auth_and_handle_payload(self, payload: EventPayload) -> None:
        if not await self._sanity_check_payload(payload):
            return
        match authenticate_payload(payload, self._token):
            case AuthResult.OK:
                await self._handle_payload(payload)
            case AuthResult.MISMATCH | AuthResult.MISSING as blocking:
                await self._dispatch_auth_issue(payload, blocking)
            case AuthResult.UNEXPECTED as nonblocking:
                await self._dispatch_auth_issue(payload, nonblocking)
                await self._handle_payload(payload)

    async def dispatch_event(
        self,
        event_type: str,
        body: dict[str, Any],
        *,
        headers: dict[str, Any] | None = None,
    ) -> None:
        """
        Dispatch a webhook event directly to registered hooks.

        Useful for testing hooks without a real GitHub webhook or SSE relay.
        Authentication is skipped by default; set a signature header to test it.
        """
        payload = cast(
            "EventPayload",
            {EVENT_HEADER: event_type, "body": body}
            | {k.casefold(): v for k, v in (headers or {}).items()},
        )
        if SIG_HEADER in payload:
            await self._auth_and_handle_payload(payload)
        elif await self._sanity_check_payload(payload):
            await self._handle_payload(payload)

    async def _dispatch_hooks(
        self,
        payload: EventPayload | None,
        event_name: str | None,
        hooks: Iterable[Hook[P]] | None,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        if hooks is None:
            return
        coros = (h(*args, **kwargs) for h in hooks)
        excs = await asyncio.gather(*coros, return_exceptions=True)
        for exc in filter(None, excs):
            if not isinstance(exc, Exception):
                # Don't handle non-Exceptions (like SystemExit or KeyboardInterrupt)
                raise exc
            await self._raise(exc, payload, event_name)
