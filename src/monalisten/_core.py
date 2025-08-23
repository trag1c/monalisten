from __future__ import annotations

import asyncio
from collections import defaultdict
from enum import Enum
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypedDict,
    TypeVar,
    cast,
    get_args,
    overload,
)

import httpx
from githubkit import webhooks
from githubkit.versions.v2022_11_28.webhooks import VALID_EVENT_NAMES
from httpx_sse import ServerSentEvent, aconnect_sse
from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from githubkit.versions.v2022_11_28.webhooks import EventNameType, WebhookEvent
    from pydantic_core import ErrorDetails
    from typing_extensions import ParamSpec, TypeAlias

    P = ParamSpec("P")
    T = TypeVar("T")
    H = TypeVar("H", bound="WebhookEvent")

    Hook: TypeAlias = Callable[P, Awaitable[None]]
    HookTrigger: TypeAlias = Literal[EventNameType, "*"]
    HookWrapper: TypeAlias = Callable[[T], T]

    MetaReadyHook: TypeAlias = Hook[[]]
    MetaAuthIssueHook: TypeAlias = "Hook[[AuthIssue, dict[str, Any]]]"
    MetaErrorHook: TypeAlias = "Hook[[dict[str, Any], str, list[ErrorDetails] | None]]"


class MetaHooks(TypedDict):
    ready: list[MetaReadyHook]
    auth_issue: list[MetaAuthIssueHook]
    error: list[MetaErrorHook]


MetaEventName: TypeAlias = Literal["ready", "auth_issue", "error"]
VALID_META_EVENT_NAMES = frozenset(get_args(MetaEventName))

EVENT_HEADER = "x-github-event"
SIG_HEADER = "x-hub-signature-256"


class AuthIssue(Enum):
    MISSING = "missing"
    """Client has set token, but no signature was received"""
    UNEXPECTED = "unexpected"
    """Client has no set token, but a signature was received"""
    MISMATCH = "mismatch"
    """Client's token couldn't verify received signature"""


class MonalistenError(Exception):
    """Exception for errors encountered by the Monalisten client."""


class Monalisten:
    """
    A Monalisten client streaming events from `source`, optionally secured by the secret
    `token`.
    """

    def __init__(self, source: str, *, token: str | None = None) -> None:
        self._source = source
        self._token = token
        self._hooks: defaultdict[HookTrigger, list[Hook]] = defaultdict(list)
        self._meta_hooks: MetaHooks = {"ready": [], "auth_issue": [], "error": []}

    @property
    def source(self) -> str:
        return self._source

    @property
    def token(self) -> str | None:
        return self._token

    async def _passes_auth(self, event_data: dict[str, Any]) -> bool:
        if not self._token:
            if SIG_HEADER in event_data:
                await self._report_auth_issue(AuthIssue.UNEXPECTED, event_data)
            return True

        if not (signature := event_data.get(SIG_HEADER)):
            await self._report_auth_issue(AuthIssue.MISSING, event_data)
            return False

        if webhooks.verify(self._token, event_data["body"], signature):
            return True

        await self._report_auth_issue(AuthIssue.MISMATCH, event_data)
        return False

    async def _report_auth_issue(
        self, issue_kind: AuthIssue, event_data: dict[str, Any]
    ) -> None:
        await dispatch_hooks(self._meta_hooks.get("auth_issue"), issue_kind, event_data)

    async def _raise(
        self,
        event_data: dict[str, Any],
        message: str,
        pydantic_errors: list[ErrorDetails] | None = None,
    ) -> None:
        if error_hooks := self._meta_hooks.get("error"):
            await dispatch_hooks(error_hooks, event_data, message, pydantic_errors)
        else:
            raise MonalistenError(message)

    @overload
    def on_internal(self, event: Literal["error"]) -> HookWrapper[MetaErrorHook]: ...

    @overload
    def on_internal(
        self, event: Literal["auth_issue"]
    ) -> HookWrapper[MetaAuthIssueHook]: ...

    @overload
    def on_internal(self, event: Literal["ready"]) -> HookWrapper[MetaReadyHook]: ...

    def on_internal(self, event: MetaEventName) -> HookWrapper[Hook[...]]:
        """Register the decorated function as a hook for the internal `event` event."""
        if event not in VALID_META_EVENT_NAMES:
            msg = f"Invalid internal event name: {event!r}"
            raise MonalistenError(msg)

        def wrapper(hook: Hook[...]) -> Hook[...]:
            self._meta_hooks[event].append(hook)
            return hook

        return wrapper

    def on(self, event: HookTrigger) -> HookWrapper[Hook[[H]]]:
        """Register the decorated function as a hook for the `event` event."""
        if event not in VALID_EVENT_NAMES and event != "*":
            msg = f"Invalid event name: {event!r}"
            raise MonalistenError(msg)

        def wrapper(hook: Hook[[H]]) -> Hook[[H]]:
            self._hooks[event].append(hook)
            return hook

        return wrapper

    def _prepare_event_data(self, event: ServerSentEvent) -> dict[str, Any]:
        return {k.casefold(): v for k, v in event.json().items()}

    async def _handle_event(self, event: ServerSentEvent) -> None:
        if not (event_data := self._prepare_event_data(event)):
            return

        if not await self._passes_auth(event_data):
            return

        if not (event_name := event_data.get(EVENT_HEADER)):
            await self._raise(
                event_data, f"received data is missing the {EVENT_HEADER} header"
            )
            return

        if not (body := event_data.get("body")):
            await self._raise(event_data, "received data doesn't contain a body")
            return

        try:
            webhook_event = cast("WebhookEvent", webhooks.parse_obj(event_name, body))
        except ValidationError as pydantic_exc:
            await self._raise(
                event_data,
                "the received payload could not be parsed as an event",
                pydantic_exc.errors(),
            )
            return

        await dispatch_hooks(
            chain.from_iterable(
                self._hooks.get(hook_kind, []) for hook_kind in (event_name, "*")
            ),
            webhook_event,
        )

    async def listen(self) -> None:
        """Start an internal HTTP client and stream events from `source`."""
        async with (
            httpx.AsyncClient(timeout=None) as client,
            aconnect_sse(client, "GET", self._source) as sse,
        ):
            await dispatch_hooks(self._meta_hooks.get("ready"))
            async for event in sse.aiter_sse():
                await self._handle_event(event)


async def dispatch_hooks(
    hooks: Iterable[Hook[P]] | None, *args: P.args, **kwargs: P.kwargs
) -> None:
    if hooks is not None:
        await asyncio.gather(*(h(*args, **kwargs) for h in hooks))
