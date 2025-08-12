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
  - [Wildcard hooks](#wildcard-hooks)
  - [Warnings & authentication behavior](#warnings--authentication-behavior)
  - [API reference](#api-reference)
  - [GitHub event type reference](#github-event-type-reference)
  - [`monalisten.types` reference](#monalistentypes-reference)
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

from monalisten import Monalisten
from monalisten.types import PushEvent

client = Monalisten("https://smee.io/aBCDef1gHijKLM2N", token="foobar")


@client.on("push")
async def log_push(event: PushEvent) -> None:
    actor = event.sender.login if event.sender else "Someone"
    print(f"{actor} pushed to the repo!")


asyncio.run(client.listen())
```

Monalisten heavily relies on the [`githubkit`][githubkit] SDK for parsing and
verifying payloads. The `monalisten.types` module (meant for type annotations)
is actually a re-export of the `githubkit.versions.v2022_11_28.webhooks` module!


### One event, multiple hooks

You can decorate several functions with the same event passed to
`Monalisten.on`, and both of them will be registered:

```py
@client.on("pull_request")
async def log_opened_pr(event: PullRequestEvent) -> None:
    if event.action != "opened":
        return
    print(f"New PR: #{event.number}")

@client.on("pull_request")
async def log_pr_action(event: PullRequestEvent) -> None:
    print(f"Something happened to PR #{event.number}!")
```

When an event type has several hooks attached, they're all run concurrently.


### One hook, multiple events

You can decorate the same function with `Monalisten.on` several times:

```py
@client.on("pull_request")
@client.on("push")
async def log_things(event: PullRequestEvent | PushEvent) -> None:
    if "PullRequest" in type(event).__name__:
        print("Something happened to a PR!")
    else:
        print("Someone pushed!")
```


### Wildcard hooks

You can define a hook to be triggered for ALL events by setting the event name
to `*`:

```py
@client.on("*")
async def log(event: WebhookEvent) -> None:
    print(f"Something definitely happened... a {type(event).__name__} perhaps")
```


### Warnings & authentication behavior

During its authentication step, Monalisten can issue warnings for unexpected
state if you pass `log_auth_warnings=True` when creating a client.

Monalisten will issue warnings in the following cases:

* the client sets a token, but:
  * the received event doesn't have a signature header
  * the received event's signature cannot be validated with the client's token

  (the event is not processed in both cases)

* the client doesn't set a token, but the received event has a signature header
  (the event is still processed)


### API reference

#### `Monalisten`

```py
class Monalisten:
    def __init__(
        self,
        source: str,
        *,
        token: str | None = None,
        log_auth_warnings: bool = False,
    ) -> None: ...
```

Creates a Monalisten client streaming events from `source`, optionally secured
by the secret `token`. For details on `log_auth_warnings`, see the
[Warnings & authentication behavior](#warnings--authentication-behavior)
section.


#### `Monalisten.listen`

```py
class Monalisten:
    async def listen(self) -> None: ...
```

Instantiates an internal HTTP client and starts streaming events from `source`.


#### `Monalisten.on`

```py
class Monalisten:
    def on(self, event: HookTrigger) -> Callable[[Hook[H]], Hook[H]]: ...
```

Meant to be used as a decorator. Registers the decorated function as a hook for
the `event` event. Raises an error if an invalid event name is provided.
`HookTrigger` is either a [GitHub event name](#github-event-type-reference) or
the [wildcard hook `"*"`](#wildcard-hooks).

In technical terms, this returns a function that registers the function passed
in as a Monalisten hook.


#### `MonalistenError`

```py
class MonalistenError(Exception): ...
```

An exception for errors encountered by the Monalisten client (e.g. invalid event
name or missing payload data).


### GitHub event name reference

For a list of event names that can be passed to `Monalisten.on`, see GitHub's
documentation page on [Webhook events and payloads][gh-events].


### `monalisten.types` reference

For a list of type names that can be used as event annotations, see the
[src/monalisten/types.py][githubkit-types] file, or, if you use one,
rely on your LSP's autocomplete!


## License
`monalisten` is licensed under the [MIT License].  
© [trag1c], 2025


[githubkit]: https://github.com/yanyongyu/githubkit
[httpx]: https://github.com/encode/httpx
[SSE]: https://en.wikipedia.org/wiki/Server-sent_events
[httpx-sse]: https://github.com/florimondmanca/httpx-sse
[smee.io]: https://smee.io/
[gh-events]: https://docs.github.com/en/webhooks/webhook-events-and-payloads
[githubkit-types]: https://github.com/trag1c/monalisten/blob/main/src/monalisten/types.py
[MIT License]: https://opensource.org/license/mit
[trag1c]: https://github.com/trag1c
