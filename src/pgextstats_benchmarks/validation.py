"""Serializable validation checks and reports for loaded instances."""
from dataclasses import dataclass, field
from typing import Any, Mapping
import json


@dataclass(frozen=True)
class ValidationCheck:
    """One named correctness check and its observed value."""

    name: str
    status: str
    expected: Any = None
    actual: Any = None
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("check name must be a nonempty string")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("check status must be a nonempty string")
        if not isinstance(self.message, str):
            raise TypeError("check message must be a string")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "name": self.name,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }
        json.dumps(value, sort_keys=True)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationCheck":
        return cls(
            name=value["name"],
            status=value["status"],
            expected=value.get("expected"),
            actual=value.get("actual"),
            message=value.get("message", ""),
        )


@dataclass(frozen=True)
class ValidationReport:
    """The complete result of validating one loaded benchmark instance."""

    benchmark_id: str
    instance_id: str
    status: str
    checks: tuple[ValidationCheck, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("benchmark_id", "instance_id", "status"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.checks, (list, tuple)):
            raise TypeError("checks must be a list or tuple")
        if not all(isinstance(check, ValidationCheck) for check in self.checks):
            raise TypeError("checks must contain ValidationCheck objects")
        if isinstance(self.checks, list):
            object.__setattr__(self, "checks", tuple(self.checks))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("validation metadata must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "benchmark_id": self.benchmark_id,
            "instance_id": self.instance_id,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "metadata": dict(self.metadata),
        }
        json.dumps(value, sort_keys=True)
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationReport":
        return cls(
            benchmark_id=value["benchmark_id"],
            instance_id=value["instance_id"],
            status=value["status"],
            checks=tuple(ValidationCheck.from_dict(item) for item in value.get("checks", ())),
            metadata=value.get("metadata", {}),
        )
