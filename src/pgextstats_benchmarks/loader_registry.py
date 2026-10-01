"""Explicit loader registry with no dynamic discovery."""
from collections.abc import Mapping
from typing import Type

from .loaders import DatabaseLoader

_LOADERS: dict[str, Type[DatabaseLoader]] = {}


def register_loader(loader_id: str, loader_class: Type[DatabaseLoader]) -> None:
    """Register one loader implementation under a stable ID."""
    if not isinstance(loader_id, str) or not loader_id.strip():
        raise ValueError("loader_id must be a nonempty string")
    if not isinstance(loader_class, type) or not issubclass(loader_class, DatabaseLoader):
        raise TypeError("loader_class must subclass DatabaseLoader")
    if loader_id in _LOADERS:
        raise ValueError(f"Loader already registered: {loader_id}")
    _LOADERS[loader_id] = loader_class


def get_loader(loader_id: str) -> Type[DatabaseLoader]:
    """Return a registered loader class or a clear error."""
    try:
        return _LOADERS[loader_id]
    except KeyError as exc:
        raise ValueError(f"No loader registered: {loader_id}") from exc


def list_loaders() -> tuple[str, ...]:
    """Return registered loader IDs in deterministic order."""
    return tuple(sorted(_LOADERS))


def registered_loaders() -> Mapping[str, Type[DatabaseLoader]]:
    """Return a copy for diagnostics without exposing mutable registry state."""
    return _LOADERS.copy()
