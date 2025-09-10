from typing import Any

from githubkit import lazy_module as lm


# HACK: githubkit's lazy module mechanism doesn't seem to support aliases in
# __lazy_vars__. This subclass implements it... may future generations forgive me.
class _MonalistenLazyModule(lm.LazyModule):
    def __getattr__(self, name: str) -> Any:
        if (
            self.__lazy_vars_validated__ is None
            or "__monalisten_sentinel__" not in self.__lazy_vars_mapping__
            or not (original_name := self.__lazy_vars_mapping__.get(name))
        ):
            return super().__getattr__(name)

        m = "webhooks" if original_name.endswith("Event") else "models"
        module = self._get_module(f"githubkit.versions.latest.{m}")
        value = getattr(module, original_name)
        setattr(self, name, value)
        return value


lm.LAZY_MODULES = (*lm.LAZY_MODULES, r"^monalisten\.events$")
lm.LazyModule = _MonalistenLazyModule
lm.apply()

from . import events
from ._core import Monalisten
from ._errors import (
    AuthIssue,
    AuthIssueKind,
    Error,
    MonalistenPreprocessingError,
    MonalistenSetupError,
)

__all__ = (
    "AuthIssue",
    "AuthIssueKind",
    "Error",
    "Monalisten",
    "MonalistenPreprocessingError",
    "MonalistenSetupError",
    "events",
)
