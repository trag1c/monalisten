from githubkit import lazy_module as lm

lm.LAZY_MODULES = (*lm.LAZY_MODULES, r"^monalisten\.types$")
lm.apply()

from . import types
from ._core import Monalisten

__all__ = ("Monalisten", "types")
