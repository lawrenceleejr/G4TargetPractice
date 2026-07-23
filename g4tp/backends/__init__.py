"""Backend registry: map a generator name to its Backend implementation.

The GENIE backend is registered lazily (its module is only importable inside the
GENIE image / dev extra), so `get('geant4')` never pays for GENIE imports.
"""
from .base import Backend, Prepared
from .geant4 import Geant4Backend

_REGISTRY = {}


def register(backend: Backend):
    _REGISTRY[backend.name] = backend


register(Geant4Backend())


def get(name: str) -> Backend:
    if name == "genie" and name not in _REGISTRY:
        try:
            from .genie import GenieBackend
            register(GenieBackend())
        except ImportError as exc:  # pragma: no cover - PR2 lands the module
            raise ValueError(f"genie backend is not available: {exc}")
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown generator {name!r}; available: {', '.join(sorted(_REGISTRY))}")


__all__ = ["Backend", "Prepared", "get", "register"]
