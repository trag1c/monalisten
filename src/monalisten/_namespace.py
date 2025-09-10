from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, Literal, NoReturn, TypeVar, cast, final

from monalisten._errors import Error, MonalistenSetupError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from typing_extensions import ParamSpec, Self, TypeAlias

    from monalisten._errors import AuthIssue

    P = ParamSpec("P")

    Hook: TypeAlias = "Callable[P, Awaitable[None]]"
    HookWrapper: TypeAlias = "Callable[[Hook[P]], Hook[P]]"


E = TypeVar("E")
L = TypeVar("L", bound=str)
InternalEventName = Literal["ready", "auth_issue", "error"]


def build_registrar(name: str) -> HookWrapper[...]:
    @property
    def prop(self: HookNamespace[Any, E]) -> Callable[[Hook[[E]]], Hook[[E]]]:
        def wrapper(hook: Hook[[E]]) -> Hook[[E]]:
            self._paths[name].append(hook)  # pyright: ignore[reportPrivateUsage]
            return hook

        return wrapper

    return cast("HookWrapper[...]", prop)


class HookNamespace(Generic[L, E]):
    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        actions = [cast("L", entry) for entry in dir(cls) if not entry.startswith("_")]

        def filling_init(self: Self) -> None:
            self._paths = {a: [] for a in actions}
            self._event_hooks = []

        cls.__init__ = filling_init

    def __init__(self) -> None:
        self._paths: dict[L, list[Hook[[E]]]] = {}
        self._event_hooks: list[Hook[[E]]] = []

    def __call__(self, hook: Hook[[E]]) -> Hook[[E]]:
        self._event_hooks.append(hook)
        return hook

    def __getitem__(self, name: L | Literal["*"]) -> list[Hook[[E]]]:
        if name == "*":
            return self._event_hooks
        return self._paths[name]


@final
class InternalNamespace(HookNamespace[InternalEventName, object]):
    ready: HookWrapper[[]] = build_registrar("ready")
    auth_issue: HookWrapper[[AuthIssue]] = build_registrar("auth_issue")
    error: HookWrapper[[Error]] = build_registrar("error")

    def __call__(self, _: object) -> NoReturn:
        msg = (
            "bare @Monalisten.internal is not allowed, please specify a concrete"
            " internal event"
        )
        raise MonalistenSetupError(msg)
