"""Deprecated compatibility shim: `g4tp` was renamed to `gdmltp`.

`import g4tp` (and `from g4tp import ...`, `from g4tp.<sub> import ...`) keep
working by aliasing onto the `gdmltp` package, with a one-time DeprecationWarning.
New code should import `gdmltp` directly. This shim will be removed after a
deprecation window.
"""
import importlib
import sys
import warnings

warnings.warn(
    "the 'g4tp' package was renamed to 'gdmltp'; import 'gdmltp' instead "
    "(the 'g4tp' alias will be removed in a future release)",
    DeprecationWarning, stacklevel=2)

import gdmltp as _gdmltp

# Re-export the top-level package and alias every submodule so that
# `from g4tp.backends import genie`, `from g4tp.io import MM_PER_CM`, etc. resolve.
_SUBMODULES = [
    "cli", "run", "config", "io", "geometry", "scene", "particles", "masses",
    "analyze", "compare", "render_web", "render_png", "render_blender",
    "backends", "backends.base", "backends.geant4", "backends.genie",
    "backends.genie_convert",
]
for _name in _SUBMODULES:
    try:
        _mod = importlib.import_module(f"gdmltp.{_name}")
        sys.modules[f"g4tp.{_name}"] = _mod
    except ImportError:
        pass

__version__ = _gdmltp.__version__
__all__ = getattr(_gdmltp, "__all__", [])


def __getattr__(name):
    # Delegate attribute access (e.g. g4tp.io) to gdmltp.
    return getattr(_gdmltp, name)
