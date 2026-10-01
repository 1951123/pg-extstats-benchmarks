"""Explicit registry for benchmark validators."""
from collections.abc import Mapping
from typing import Type

from .validators import BenchmarkValidator

_VALIDATORS: dict[str, Type[BenchmarkValidator]] = {}


def register_validator(validator_id: str, validator_class: Type[BenchmarkValidator]) -> None:
    """Register one validator under a stable explicit ID."""
    if not isinstance(validator_id, str) or not validator_id.strip():
        raise ValueError("validator_id must be a nonempty string")
    if not isinstance(validator_class, type) or not issubclass(
        validator_class, BenchmarkValidator
    ):
        raise TypeError("validator_class must subclass BenchmarkValidator")
    if validator_id in _VALIDATORS:
        raise ValueError(f"Validator already registered: {validator_id}")
    _VALIDATORS[validator_id] = validator_class


def get_validator(validator_id: str) -> Type[BenchmarkValidator]:
    """Return a registered validator class or a clear error."""
    try:
        return _VALIDATORS[validator_id]
    except KeyError as exc:
        raise ValueError(f"No validator registered: {validator_id}") from exc


def list_validators() -> tuple[str, ...]:
    """Return registered validator IDs in deterministic order."""
    return tuple(sorted(_VALIDATORS))


def registered_validators() -> Mapping[str, Type[BenchmarkValidator]]:
    """Return a copy for diagnostics without exposing mutable registry state."""
    return _VALIDATORS.copy()
