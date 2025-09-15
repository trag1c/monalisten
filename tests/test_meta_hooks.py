from __future__ import annotations

import copy
import sys
import textwrap
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from monalisten import AuthIssue, Error, Monalisten, MonalistenPreprocessingError
from monalisten._core import EVENT_HEADER, SIG_HEADER
from tests.ghk_utils import DUMMY_AUTH_EVENT, sign_auth_event

if TYPE_CHECKING:
    from .sse_server import ServerQueue


@pytest.mark.asyncio
async def test_on_ready(
    sse_server: tuple[ServerQueue, str], capsys: pytest.CaptureFixture[str]
) -> None:
    queue, url = sse_server
    await queue.end_signal()

    client = Monalisten(url)

    @client.internal.ready
    async def _() -> None:
        print("hello")

    @client.internal.ready
    async def _() -> None:
        print("there")

    await client.listen()

    printed_messages = capsys.readouterr().out.split()
    assert sorted(printed_messages) == ["hello", "there"]


@pytest.mark.asyncio
async def test_on_auth_issue(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event(DUMMY_AUTH_EVENT)
    await queue.send_event(DUMMY_AUTH_EVENT | {SIG_HEADER: sign_auth_event("wrong")})
    await queue.end_signal()

    client = Monalisten(url, token="foobar")
    issue_names: list[str] = []

    @client.internal.auth_issue
    async def _(issue: AuthIssue) -> None:
        issue_names.append(issue.kind.value)

    await client.listen()

    assert sorted(issue_names) == ["mismatch", "missing"]


@pytest.mark.parametrize(
    ("event", "err_msg"),
    [
        ({"foo": "bar"}, f"received data is missing the {EVENT_HEADER} header"),
        ({EVENT_HEADER: "push"}, "received data doesn't contain a body"),
        (
            {EVENT_HEADER: "push", "body": {"foo": "bar"}},
            "the received payload could not be parsed as an event",
        ),
    ],
)
@pytest.mark.asyncio
async def test_no_error_hook(
    sse_server: tuple[ServerQueue, str], event: dict[str, Any], err_msg: str
) -> None:
    queue, url = sse_server
    await queue.send_event(event)
    await queue.end_signal()

    client = Monalisten(url)

    with pytest.raises(MonalistenPreprocessingError, match=err_msg):
        await client.listen()


@pytest.mark.parametrize(
    ("event", "err_msg"),
    [
        ({"foo": "bar"}, f"received data is missing the {EVENT_HEADER} header"),
        ({EVENT_HEADER: "push"}, "received data doesn't contain a body"),
        (
            {EVENT_HEADER: "push", "body": {"foo": "bar"}},
            "the received payload could not be parsed as an event",
        ),
    ],
)
@pytest.mark.asyncio
async def test_on_error_preprocessing(
    sse_server: tuple[ServerQueue, str], event: dict[str, Any], err_msg: str
) -> None:
    queue, url = sse_server
    await queue.send_event(event)
    await queue.end_signal()

    client = Monalisten(url)

    @client.internal.error
    async def _(error: Error) -> None:
        assert isinstance(error.exc, MonalistenPreprocessingError)
        assert error.event_data == event
        assert str(error.exc) == err_msg

    await client.listen()


@pytest.mark.asyncio
async def test_handling_pydantic_errors(
    sse_server: tuple[ServerQueue, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue, url = sse_server
    bad_event = copy.deepcopy(DUMMY_AUTH_EVENT)
    del bad_event["body"]["sender"]["login"]
    del bad_event["body"]["action"]

    await queue.send_event(bad_event)
    await queue.end_signal()

    client = Monalisten(url)

    @client.internal.error
    async def _(error: Error) -> None:
        print(str(error.exc))
        cause = error.exc.__cause__
        assert isinstance(cause, ValidationError)
        for err in cause.errors():
            print("-", err["msg"])
            print(" ", err["loc"])

    await client.listen()

    assert capsys.readouterr().out == textwrap.dedent(
        """\
        the received payload could not be parsed as an event
        - Field required
          ('action',)
        - Field required
          ('sender', 'login')
        """
    )


@pytest.mark.asyncio
async def test_on_error_processing(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.send_event({"foo": "bar"})
    await queue.end_signal()

    client = Monalisten(url, token="foobar")

    messages = set[str]()

    @client.internal.ready
    async def _() -> None:
        messages.add("ready")
        print(int("a"))

    @client.internal.auth_issue
    async def _(auth_issue: AuthIssue) -> None:
        messages.add(f"auth issue: {auth_issue.kind.value}")
        print(1 / 0)

    @client.internal.error
    async def _(error: Error) -> None:
        messages.add(f"error in event {error.event_name}")

    await client.listen()

    assert messages == {
        "ready",
        "auth issue: missing",
        "error in event ready",
        "error in event auth_issue",
    }


@pytest.mark.asyncio
async def test_on_error_self_loop(sse_server: tuple[ServerQueue, str]) -> None:
    queue, url = sse_server
    await queue.end_signal()

    client = Monalisten(url)

    @client.internal.ready
    async def _() -> None:
        print(1 / 0)

    @client.internal.error
    async def _(_: Error) -> None:
        print(1 / 0)

    warn = pytest.warns(RuntimeWarning) if sys.version_info < (3, 10) else nullcontext()
    with warn, pytest.raises(RecursionError):
        await client.listen()
