from __future__ import annotations

import copy
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from monalisten import AuthIssue, Monalisten, MonalistenError
from monalisten._core import EVENT_HEADER, SIG_HEADER
from tests.ghk_utils import DUMMY_AUTH_EVENT, sign_auth_event

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from .sse_server import ServerQueue


def test_invalid_event_name() -> None:
    with pytest.raises(MonalistenError, match="Invalid internal event name: 'rbob'"):

        @Monalisten("").on_internal("rbob")  # pyright: ignore [reportArgumentType, reportCallIssue]
        async def _(_: str) -> None:
            pass


@pytest.mark.asyncio
async def test_on_ready(
    sse_server: tuple[ServerQueue, str], capsys: pytest.CaptureFixture[str]
) -> None:
    queue, url = sse_server
    await queue.end_signal()

    client = Monalisten(url)

    @client.on_internal("ready")
    async def _() -> None:
        print("hello")

    @client.on_internal("ready")
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

    @client.on_internal("auth_issue")
    async def _(issue: AuthIssue, _: dict[str, Any]) -> None:
        issue_names.append(issue.value)

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

    with pytest.raises(MonalistenError, match=err_msg):
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
async def test_on_error(
    sse_server: tuple[ServerQueue, str], event: dict[str, Any], err_msg: str
) -> None:
    queue, url = sse_server
    await queue.send_event(event)
    await queue.end_signal()

    client = Monalisten(url)

    @client.on_internal("error")
    async def _(e: dict[str, Any], message: str, _: list[ErrorDetails] | None) -> None:
        assert e == event
        assert message == err_msg

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

    @client.on_internal("error")
    async def _(
        _: dict[str, Any],
        message: str,
        pydantic_errors: list[ErrorDetails] | None,
    ) -> None:
        print(message)
        for err in pydantic_errors or []:
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
