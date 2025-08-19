from __future__ import annotations

import asyncio
import warnings
from collections import defaultdict
from itertools import chain
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

import httpx
from githubkit import webhooks
from githubkit.versions.v2022_11_28.webhooks import VALID_EVENT_NAMES
from httpx_sse import ServerSentEvent, aconnect_sse
from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from githubkit.versions.v2022_11_28.webhooks import EventNameType, WebhookEvent
    from typing_extensions import TypeAlias

H = TypeVar("H", bound="WebhookEvent")
Hook: TypeAlias = "Callable[[H], Awaitable[None]]"
HookTrigger: TypeAlias = 'Literal[EventNameType, "*"]'

GUID_HEADER = "x-github-delivery"
EVENT_HEADER = "x-github-event"
SIG_HEADER = "x-hub-signature-256"


class MonalistenError(Exception):
    """Exception for errors encountered by the Monalisten client."""


class Monalisten:
    """
    A Monalisten client streaming events from `source`, optionally secured by the secret
    `token`. For details on `log_auth_warnings`, see the "Warnings & authentication
    behavior" section of the documentation.
    """

    def __init__(
        self, source: str, *, token: str | None = None, log_auth_warnings: bool = False
    ) -> None:
        self._source = source
        self._token = token
        self._log = log_auth_warnings
        self._hooks = defaultdict[HookTrigger, list[Hook]](list)

    def _passes_auth(self, event_data: dict[str, Any]) -> bool:
        if not self._token:
            if SIG_HEADER in event_data:
                self._warn(
                    event_data, f"Received {SIG_HEADER} header, but no token was set"
                )
            return True

        if not (signature := event_data.get(SIG_HEADER)):
            self._warn(event_data, f"Missing {SIG_HEADER} header")
            return False

        if webhooks.verify(self._token, event_data["body"], signature):
            return True

        self._warn(event_data, f"{SIG_HEADER} header does not match set token")
        return False

    def _warn(self, event_data: dict[str, Any], message: str) -> None:
        if not self._log:
            return
        name = event_data.get(EVENT_HEADER, "unknown")
        guid = event_data.get(GUID_HEADER, "unknown")
        warnings.warn(f"Event {name} ({guid}): {message}", stacklevel=3)

    def on(self, event: HookTrigger) -> Callable[[Hook[H]], Hook[H]]:
        """Register the decorated function as a hook for the `event` event."""
        if event not in VALID_EVENT_NAMES and event != "*":
            msg = f"Invalid event name: {event!r}"
            raise MonalistenError(msg)

        def wrapper(hook: Hook[H]) -> Hook[H]:
            self._hooks[event].append(hook)
            return hook

        return wrapper

    def _prepare_event_data(self, event: ServerSentEvent) -> dict[str, Any]:
        return {k.casefold(): v for k, v in event.json().items()}

    async def _handle_event(self, event: ServerSentEvent) -> None:
        if not (event_data := self._prepare_event_data(event)):
            return

        if not self._passes_auth(event_data):
            return

        if not (event_name := event_data.get(EVENT_HEADER)):
            msg = f"received data is missing the {EVENT_HEADER} header"
            raise MonalistenError(msg)

        if not (body := event_data.get("body")):
            msg = "received data doesn't contain a body"
            raise MonalistenError(msg)

        try:
            webhook_event = cast("WebhookEvent", webhooks.parse_obj(event_name, body))
        except ValidationError as pydantic_exc:
            msg = "the received payload could not be parsed as an event"
            raise MonalistenError(msg) from pydantic_exc

        coros = (
            hook(webhook_event)
            for hook in chain.from_iterable(
                self._hooks.get(hook_kind, []) for hook_kind in (event_name, "*")
            )
        )
        await asyncio.gather(*coros)

    async def listen(self) -> None:
        """Start an internal HTTP client and stream events from `source`."""
        async with (
            httpx.AsyncClient(timeout=None) as client,
            aconnect_sse(client, "GET", self._source) as sse,
        ):
            async for event in sse.aiter_sse():
                await self._handle_event(event)
