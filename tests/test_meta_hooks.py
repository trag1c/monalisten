from __future__ import annotations

import copy
import textwrap
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from monalisten import Monalisten, MonalistenPreprocessingError
from monalisten._auth import SIG_HEADER
from monalisten._core import EVENT_HEADER
from tests.ghk_utils import DUMMY_AUTH_EVENT, sign_auth_event

from .server_utils import listen_until

if TYPE_CHECKING:
    from monalisten import AuthResult, Error, EventPayload, events

    from .server_utils import Server


async def test_on_ready(
    server: tuple[Server, str], capsys: pytest.CaptureFixture[str]
) -> None:
    queue, url = server
    await queue.end_signal()

    client = Monalisten(url)
    ready_count = 0

    @client.internal.ready
    async def _() -> None:
        nonlocal ready_count
        ready_count += 1
        print("hello")

    @client.internal.ready
    async def _() -> None:
        nonlocal ready_count
        ready_count += 1
        print("there")

    await listen_until(client, lambda: ready_count == 2)

    printed_messages = capsys.readouterr().out.split()
    assert sorted(printed_messages) == ["hello", "there"]


async def test_on_auth_issue(server: tuple[Server, str]) -> None:
    queue, url = server
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.send_event(DUMMY_AUTH_EVENT | {SIG_HEADER: sign_auth_event("wrong")})
    await queue.end_signal()

    client = Monalisten(url, token="foobar")
    issue_names: list[str] = []

    @client.internal.auth_issue
    async def _(_: EventPayload, result: AuthResult) -> None:
        issue_names.append(result.value)

    await listen_until(client, lambda: len(issue_names) == 2)

    assert sorted(issue_names) == ["mismatch", "missing"]


@pytest.mark.parametrize(
    ("event", "err_msg"),
    [
        (
            {"x-github-delivery": "123"},
            f"received data is missing the {EVENT_HEADER} header",
        ),
        (
            {EVENT_HEADER: "push"},
            "received data doesn't contain a valid JSON object body",
        ),
    ],
)
async def test_no_error_hook(
    server: tuple[Server, str], event: dict[str, Any], err_msg: str
) -> None:
    queue, url = server
    await queue.send_event(event)
    await queue.end_signal()

    client = Monalisten(url)

    with pytest.raises(MonalistenPreprocessingError, match=err_msg):
        await client.listen()


async def test_no_error_hook_no_preprocessing_trigger_on_unused_event(
    server: tuple[Server, str],
) -> None:
    queue, url = server
    await queue.send_event({EVENT_HEADER: "push", "body": {"foo": "bar"}})
    await queue.end_signal()

    client = Monalisten(url)
    processed = 0
    original = client._auth_and_handle_payload

    async def spy(payload: EventPayload) -> None:
        nonlocal processed
        processed += 1
        await original(payload)

    client._auth_and_handle_payload = spy  # ty:ignore[invalid-assignment]

    await listen_until(client, lambda: processed == 1)


async def test_no_error_hook_preprocessing_trigger_on_used_event(
    server: tuple[Server, str],
) -> None:
    queue, url = server
    await queue.send_event({EVENT_HEADER: "push", "body": {"foo": "bar"}})
    await queue.end_signal()

    client = Monalisten(url)

    @client.event.push
    async def _(_: events.Push) -> None:
        pass

    with pytest.raises(
        MonalistenPreprocessingError,
        match="the received payload could not be parsed as an event",
    ):
        await client.listen()


@pytest.mark.parametrize(
    ("event", "err_msg"),
    [
        (
            {"x-github-delivery": "123"},
            f"received data is missing the {EVENT_HEADER} header",
        ),
        (
            {EVENT_HEADER: "push"},
            "received data doesn't contain a valid JSON object body",
        ),
        (
            {EVENT_HEADER: "push", "body": {"foo": "bar"}},
            "the received payload could not be parsed as an event",
        ),
    ],
)
async def test_on_error_preprocessing(
    server: tuple[Server, str], event: dict[str, Any], err_msg: str
) -> None:
    queue, url = server
    await queue.send_event(event)
    await queue.end_signal()

    client = Monalisten(url)

    errors_seen = 0

    @client.internal.error
    async def _(error: Error) -> None:
        nonlocal errors_seen
        assert isinstance(error.exc, MonalistenPreprocessingError)
        assert error.payload == event
        assert str(error.exc) == err_msg
        errors_seen += 1

    # The last parametrized event fires no error hook (no event hook is registered,
    # so the payload is never parsed) -- spy on processing for the completion signal.
    processed = 0
    original = client._auth_and_handle_payload

    async def spy(payload: EventPayload) -> None:
        nonlocal processed
        processed += 1
        await original(payload)

    client._auth_and_handle_payload = spy  # ty:ignore[invalid-assignment]

    await listen_until(client, lambda: processed == 1)


async def test_handling_pydantic_errors(
    server: tuple[Server, str], capsys: pytest.CaptureFixture[str]
) -> None:
    queue, url = server
    bad_event = copy.deepcopy(DUMMY_AUTH_EVENT)
    del bad_event["body"]["sender"]["login"]  # ty:ignore[invalid-argument-type, not-subscriptable]
    del bad_event["body"]["action"]  # ty:ignore[not-subscriptable]

    await queue.send_event(bad_event)
    await queue.end_signal()

    client = Monalisten(url)

    @client.event.github_app_authorization
    async def _(_: events.GithubAppAuthorization) -> None:
        pass

    handled = False

    @client.internal.error
    async def _(error: Error) -> None:
        nonlocal handled
        print(str(error.exc))
        cause = error.exc.__cause__
        assert isinstance(cause, ValidationError)
        for err in cause.errors():
            print("-", err["msg"])
            print(" ", err["loc"])
        handled = True

    await listen_until(client, lambda: handled)

    assert capsys.readouterr().out == textwrap.dedent(
        """\
        the received payload could not be parsed as an event
        - Field required
          ('action',)
        - Field required
          ('sender', 'login')
        """
    )


async def test_on_error_processing(server: tuple[Server, str]) -> None:
    queue, url = server
    await queue.send_event({EVENT_HEADER: "bar", "body": {"foo": "bar"}})
    await queue.end_signal()

    client = Monalisten(url, token="foobar")

    messages = set[str]()

    @client.internal.ready
    async def _() -> None:
        messages.add("ready")
        print(int("a"))

    @client.internal.auth_issue
    async def _(_: EventPayload, result: AuthResult) -> None:
        messages.add(f"auth issue: {result.value}")
        print(1 / 0)

    @client.internal.error
    async def _(error: Error) -> None:
        messages.add(f"error in event {error.event_name}")

    await listen_until(client, lambda: len(messages) == 4)

    assert messages == {
        "ready",
        "auth issue: missing",
        "error in event ready",
        "error in event auth_issue",
    }


async def test_on_error_self_loop(server: tuple[Server, str]) -> None:
    queue, url = server
    await queue.end_signal()

    client = Monalisten(url)

    @client.internal.ready
    async def _() -> None:
        print(1 / 0)

    @client.internal.error
    async def _(_: Error) -> None:
        print(1 / 0)

    with pytest.raises(RecursionError):
        await client.listen()
