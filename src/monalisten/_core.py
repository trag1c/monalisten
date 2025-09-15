from __future__ import annotations

import asyncio
from itertools import chain
from typing import TYPE_CHECKING, Any, cast, final

import httpx
from githubkit import webhooks
from httpx_sse import ServerSentEvent, aconnect_sse
from pydantic import ValidationError

from monalisten._errors import (
    AuthIssue,
    AuthIssueKind,
    Error,
    MonalistenPreprocessingError,
)
from monalisten._event_namespace import EventNamespace
from monalisten._namespace import InternalNamespace

if TYPE_CHECKING:
    from collections.abc import Iterable

    from typing_extensions import ParamSpec

    from monalisten import events
    from monalisten._namespace import Hook

    P = ParamSpec("P")

EVENT_HEADER = "x-github-event"
SIG_HEADER = "x-hub-signature-256"


@final
class Monalisten:
    """
    A Monalisten client streaming events from `source`, optionally secured by the secret
    `token`.
    """

    def __init__(self, source: str, *, token: str | None = None) -> None:
        self._source = source
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
    def source(self) -> str:
        return self._source

    @property
    def token(self) -> str | None:
        return self._token

    async def _passes_auth(self, event_data: dict[str, Any]) -> bool:
        if not self._token:
            if SIG_HEADER in event_data:
                await self._report_auth_issue(AuthIssueKind.UNEXPECTED, event_data)
            return True

        if not (signature := event_data.get(SIG_HEADER)):
            await self._report_auth_issue(AuthIssueKind.MISSING, event_data)
            return False

        if webhooks.verify(self._token, event_data["body"], signature):
            return True

        await self._report_auth_issue(AuthIssueKind.MISMATCH, event_data)
        return False

    async def _report_auth_issue(
        self, issue_kind: AuthIssueKind, event_data: dict[str, Any]
    ) -> None:
        await self._dispatch_hooks(
            event_data,
            "auth_issue",
            self.internal["auth_issue"],
            AuthIssue(issue_kind, event_data),
        )

    async def _raise(
        self,
        exc: Exception,
        event_data: dict[str, Any] | None = None,
        event_name: str | None = None,
    ) -> None:
        if event_data:
            event_name = event_name or event_data.get(EVENT_HEADER)
        if not (error_hooks := self.internal["error"]):
            raise exc
        await self._dispatch_hooks(
            event_data, event_name, error_hooks, Error(exc, event_name, event_data)
        )

    def _prepare_event_data(self, event: ServerSentEvent) -> dict[str, Any]:
        return {k.casefold(): v for k, v in event.json().items()}

    async def _handle_event(self, event: ServerSentEvent) -> None:
        if not (event_data := self._prepare_event_data(event)):
            return

        if not await self._passes_auth(event_data):
            return

        if not (event_name := event_data.get(EVENT_HEADER)):
            msg = f"received data is missing the {EVENT_HEADER} header"
            await self._raise(MonalistenPreprocessingError(msg), event_data)
            return

        if not (body := event_data.get("body")):
            msg = "received data doesn't contain a body"
            await self._raise(MonalistenPreprocessingError(msg), event_data, event_name)
            return

        try:
            webhook_event = cast("events.Any", webhooks.parse_obj(event_name, body))
        except ValidationError as pydantic_exc:
            msg = "the received payload could not be parsed as an event"
            exc = MonalistenPreprocessingError(msg)
            exc.__cause__ = pydantic_exc
            await self._raise(exc, event_data, event_name)
            return

        hook_kinds = [self.event.any["*"], self.event[event_name]["*"]]
        if action := body.get("action"):
            hook_kinds.append(self.event[event_name][action])
        await self._dispatch_hooks(
            event_data, event_name, chain.from_iterable(hook_kinds), webhook_event
        )

    async def listen(self) -> None:
        """Start an internal HTTP client and stream events from `source`."""
        async with (
            httpx.AsyncClient(timeout=None) as client,
            aconnect_sse(client, "GET", self._source) as sse,
        ):
            await self._dispatch_hooks(
                None, "ready", cast("list[Hook[[]]]", self.internal["ready"])
            )
            async for event in sse.aiter_sse():
                await self._handle_event(event)

    async def _dispatch_hooks(
        self,
        event_data: dict[str, Any] | None,
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
                # Don't handle non-Exceptions (like SystemExits or KeyboardInterrupts)
                raise exc
            await self._raise(exc, event_data, event_name)
