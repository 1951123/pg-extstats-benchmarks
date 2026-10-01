"""Explicit benchmark adapter registry."""
from collections.abc import Mapping
from typing import Type

from .adapter import BenchmarkAdapter

_ADAPTERS: dict[str, Type[BenchmarkAdapter]] = {}


def register_adapter(benchmark_id: str, adapter_class: Type[BenchmarkAdapter]) -> None:
    """Register one adapter class under a benchmark ID.

    Registration is explicit and process-local. Duplicate IDs are rejected so
    that a later import cannot silently replace the implementation in use.
    """
    if not isinstance(benchmark_id, str) or not benchmark_id.strip():
        raise ValueError("benchmark_id must be a nonempty string")
    if not isinstance(adapter_class, type) or not issubclass(adapter_class, BenchmarkAdapter):
        raise TypeError("adapter_class must subclass BenchmarkAdapter")
    if benchmark_id in _ADAPTERS:
        raise ValueError(f"Adapter already registered: {benchmark_id}")
    _ADAPTERS[benchmark_id] = adapter_class


def get_adapter(benchmark_id: str) -> Type[BenchmarkAdapter]:
    """Return the registered adapter class for ``benchmark_id``."""
    try:
        return _ADAPTERS[benchmark_id]
    except KeyError as exc:
        raise ValueError(f"No adapter registered for benchmark: {benchmark_id}") from exc


def list_adapters() -> tuple[str, ...]:
    """Return registered benchmark IDs in deterministic order."""
    return tuple(sorted(_ADAPTERS))


def registered_adapters() -> Mapping[str, Type[BenchmarkAdapter]]:
    """Expose a read-only view for diagnostics and tests."""
    return _ADAPTERS.copy()
