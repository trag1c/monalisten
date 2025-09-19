[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# Monalisten

Monalisten is a Python 3.9+ asynchronous library that helps you handle webhook
events received from GitHub in an easy way. It is built on top of the amazing
[`githubkit`][githubkit] and [`httpx`][httpx] libraries and relies on [SSE]
(with [`httpx-sse`][httpx-sse]) to stream events without exposing any endpoints.

- [Installation](#installation)
- [Usage](#usage)
  - [Foreword on how this works](#foreword-on-how-this-works)
  - [Basic example](#basic-example)
  - [One event, multiple hooks](#one-event-multiple-hooks)
  - [One hook, multiple events](#one-hook-multiple-events)
  - [Action-specific hooks (subhooks)](#action-specific-hooks-subhooks)
  - [Wildcard hooks](#wildcard-hooks)
  - [Internal events](#internal-events)
  - [API reference](#api-reference)
  - [GitHub event type reference](#github-event-type-reference)
  - [`monalisten.event` reference](#monalistenevent-reference)
- [License](#license)

## Installation

`monalisten` is available on PyPI and can be installed with any package manager:

```sh
pip install monalisten
# or
poetry add monalisten
# or
uv add monalisten
```

You can also install it from source:

```sh
pip install git+https://github.com/trag1c/monalisten.git
```


## Usage

### Foreword on how this works

GitHub webhooks can only send event data to publicly accessible HTTP endpoints.
If your environment is behind a firewall, or a NAT, or you simply don't want to
set up a server, you can use a relay service, like [smee.io]. It generates a
unique relay URL to which GitHub sends requests to, and the relay then streams
them to your local client via SSE. Monalisten connects to the relay's SSE URL
and receives events as they arrive without any direct incoming connection to
your machine.

> [!warning]
> Relay URLs are essentially private endpoints. Anyone who knows your relay URL
> can send forged events. To mitigate this, configure a **webhook secret** in
> your GitHub repository or organization webhook settings. Pass the same secret
> to Monalisten through the `token` parameter. Now, Monalisten will validate
> incoming payloads and discard invalid ones.


### Basic example

```py
import asyncio

from monalisten import Monalisten, events

client = Monalisten("https://smee.io/aBCDef1gHijKLM2N", token="foobar")


@client.event.push
async def log_push(event: events.Push) -> None:
    actor = event.sender.login if event.sender else "Someone"
    print(f"{actor} pushed to the repo!")


asyncio.run(client.listen())
```

Monalisten heavily relies on the [`githubkit`][githubkit] SDK for parsing and
verifying payloads. The `monalisten.events` module (meant for type annotations)
is actually a re-export of two `githubkit` modules!


### One event, multiple hooks

You can decorate several functions with the same event, and both of them will be
registered:

```py
@client.event.pull_request
async def log_opened_pr(event: events.PullRequest) -> None:
    if event.action != "opened":
        return
    print(f"New PR: #{event.number}")

@client.event.pull_request
async def log_pr_action(event: events.PullRequest) -> None:
    print(f"Something happened to PR #{event.number}!")
```

When an event type has several hooks attached, they're all run concurrently.


### One hook, multiple events

You can decorate the same function with multiple events:

```py
@client.event.pull_request
@client.event.push
async def log_things(event: events.PullRequest | events.Push) -> None:
    if "PullRequest" in type(event).__name__:
        print("Something happened to a PR!")
    else:
        print("Someone pushed!")
```

> [!warning]
> **Known issue:** Due to the way event namespaces are annotated, subsequent
> decorators may get flagged by type checkers. In the example above, because of
> `@client.event.push`, `@client.event.pull_request` sees the decorated function
> as `async (events.Push) -> None`. This still works correctly at runtime, but
> you may need to add an error suppression comment to satisfy your type checker.


### Action-specific hooks (subhooks)

Monalisten allows registering hooks for a specific event action. The example in
[One event, multiple hooks](#one-event-multiple-hooks) could be rewritten as:

```py
@client.event.pull_request.opened
async def log_opened_pr(event: events.PullRequestOpened) -> None:
    print(f"New PR: #{event.number}")

@client.event.pull_request
async def log_pr_action(event: events.PullRequest) -> None:
    print(f"Something happened to PR #{event.number}!")
```

Note that some events:
* don't have any actions (e.g. `fork` or `push`), or
* only have one action (e.g. `watch` or `commit_comment`), in which case
  `@client.event.event_name.action_name` and `@client.event.event_name` are
  eqiuvalent.


### Wildcard hooks

You can define a hook to be triggered for ALL events by using the `any` event:

```py
@client.event.any
async def log(event: events.Any) -> None:
    print(f"Something definitely happened... a {type(event).__name__} perhaps")
```


### Internal events

Other than GitHub events, hooks can be created for handling a few internal
events reported by Monalisten itself, such as:
* an HTTP client is created in `.listen()` (`ready`)
* an authentication issue arises (`auth_issue`)
* an error occurs (`error`)

Internal event hooks are defined with the `Monalisten.internal` namespace. The
internal `error` event is the only one with default behavior—it will raise an
exception and halt the client. The other two are simply ignored if no hook is
defined.


#### `ready`

Triggered when an internal HTTP client is created, right before streaming events
from `source`. The expected hook signature is `async () -> None`.

```py
@client.internal.ready
async def on_ready() -> None:
    print("🚀 Monalisten is ready!")
```


#### `auth_issue`

During its authentication step, Monalisten can report issues for unexpected
state. Reading those requires defining an auth issue hook. The expected hook
signature is `async (AuthIssue) -> None`.

```py
import json
from pathlib import Path

from monalisten import AuthIssue

saved_events_dir = Path("/path/to/logs")

@client.internal.auth_issue
async def log_and_save(issue: AuthIssue) -> None:
    data = issue.payload
    event_guid = data.get("x-github-delivery", "missing-guid")
    print(f"Auth issue in event {data}: token {issue.kind.value}")
    (saved_events_dir / f"{event_guid}.json").write_text(json.dumps(data))
```

Monalisten will report auth issues in the following cases:

* the client sets a token, but:
  * the received event doesn't have a signature header
  * the received event's signature cannot be validated with the client's token

  (the event is not processed in both cases)

* the client doesn't set a token, but the received event has a signature header
  (the event is still processed)


#### `error`

Monalisten can raise an exception in three contexts:
* during setup, when attempting to register a hook under the bare
  `Monalisten.event` or `Monalisten.internal` namespaces,
* during event preprocessing, when the event payload is missing crucial fields,
  e.g. an event type header or a body,
* during event processing, when an error is raised in a user-defined hook.

Only preprocessing and processing errors can have hooks set up (since setup
errors are raised before the client is ready). The expected hook signature is
`async (Error) -> None`.

```py
from monalisten import Error
from pydantic import ValidationError

@client.internal.error
async def print_error_summary(error: Error) -> None:
    if error.payload:
        event_guid = error.payload.get("x-github-delivery", "<missing-guid>")
        print(f"An error occurred in event {event_guid}: {str(error.exc)}")
    else:
        # payload is not present if the error comes from a `ready` hook
        print("An error occurred at startup!")

    if not isinstance(cause := error.exc.__cause__, ValidationError):
        return

    print("Pydantic errors detected:")
    for err in cause.errors():
        print("-", err["msg"])
        print(" ", err["loc"])
```

> [!warning]
> Exceptions raised in the `error` hook are also handled by the `error` hook,
> which can lead to an unhandled `RecursionError` and the original error being
> lost.


### API reference

#### `AuthIssue`

```py
class AuthIssue(NamedTuple):
    kind: AuthIssueKind
    payload: EventPayload
```

An object representing authentication issue events reported by the Monalisten
client to `auth_issue` hooks.


#### `AuthIssueKind`

```py
class AuthIssueKind(Enum):
    MISSING = "missing"
    UNEXPECTED = "unexpected"
    MISMATCH = "mismatch"
```

An enum representing authentication issue kinds that can be encountered by the
Monalisten client. The table below describes scenarios in which the issue kinds
can occur:

| Issue kind   | Client token | Received signature | Verified |
| :---         | :---:        | :---:              | :---:    |
| `MISSING`    | ✅           | ❌                 | —        |
| `UNEXPECTED` | ❌           | ✅                 | —        |
| `MISMATCH`   | ✅           | ✅                 | ❌       |


#### `Error`

```py
class Error(NamedTuple):
    exc: Exception
    event_name: str | None
    payload: EventPayload
```

An object representing runtime (that is, preprocessing or processing) error
events reported by the Monalisten client.


#### `EventPayload`

```py
EventPayload = TypedDict(
    "EventPayload",
    {
        "body": dict[str, Any],
        "x-github-hook-id": str,
        "x-github-event": str,
        "x-github-delivery": str,
        "x-hub-signature": str,
        "x-hub-signature-256": str,
        "user-agent": str,
        "x-github-hook-installation-target-type": str,
        "x-github-hook-installation-target-id": str,
    },
)
```

Represents the raw event payload received from GitHub. Can be accessed in
`internal.auth_issue` and `internal.error` hooks. It only lists `body` and
headers considered "special" by GitHub (see the "Delivery headers" section of
their [Webhook events and payloads][gh-events] page), although other headers may
be present.


#### `Monalisten`

```py
class Monalisten:
    def __init__(self, source: str, *, token: str | None = None) -> None: ...
```

Creates a Monalisten client streaming events from `source`, optionally secured
by the secret `token`.


#### `Monalisten.listen`

```py
class Monalisten:
    async def listen(self) -> None: ...
```

Instantiates an internal HTTP client and starts streaming events from `source`.


#### `Monalisten.event`

A namespace storing GitHub event registrars. Valid event names are all
[GitHub event names](#github-event-type-reference) and `any`.

Every hook is expected to have the signature of `async (events.Any) -> None`
(narrowed down to the specific event type).


#### `Monalisten.internal`

A namespace storing internal event registrars. Valid event names are `ready`,
`auth_issue`, and `error`.

See the [Internal events](#internal-events) section for expected hook
signatures for each event.


#### `MonalistenPreprocessingError`

```py
class MonalistenPreprocessingError(Exception): ...
```

An exception for preprocessing errors. Triggered when the received event payload
is missing crucial fields, e.g. an event type header or a body.


#### `MonalistenSetupError`

```py
class MonalistenSetupError(Exception): ...
```

An exception for setup errors. Triggered when attempting to register a hook
under the bare `Monalisten.event` or `Monalisten.internal` namespaces.


### GitHub event name reference

For a list of valid event names under the `Monalisten.event` namespace, rely on
your LSP's autocomplete (if you use one), or see GitHub's documentation page on
[Webhook events and payloads][gh-events]. Each event may optionally include a
list of possible actions to use in [subhooks](#action-specific-hooks-subhooks).


### `monalisten.event` reference

For a list of type names that can be used as event annotations, see the
[src/monalisten/events.py][githubkit-types] file, or, if you use one, rely on
your LSP's autocomplete!


## License
`monalisten` is licensed under the [MIT License].
© [trag1c], 2025


[githubkit]: https://github.com/yanyongyu/githubkit
[httpx]: https://github.com/encode/httpx
[SSE]: https://en.wikipedia.org/wiki/Server-sent_events
[httpx-sse]: https://github.com/florimondmanca/httpx-sse
[smee.io]: https://smee.io/
[gh-events]: https://docs.github.com/en/webhooks/webhook-events-and-payloads
[githubkit-types]: https://github.com/trag1c/monalisten/blob/main/src/monalisten/events.py
[MIT License]: https://opensource.org/license/mit
[trag1c]: https://github.com/trag1c
