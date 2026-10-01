"""Metadata-only validator for the example memory instance."""
from .instances import LoadedInstance
from .validation import ValidationCheck, ValidationReport
from .validator_registry import register_validator
from .validators import BenchmarkValidator


class ExampleValidator(BenchmarkValidator):
    """Check that the example instance exists and is READY."""

    def validate_instance(self, instance: LoadedInstance) -> ValidationReport:
        if not isinstance(instance, LoadedInstance):
            raise TypeError("instance must be a LoadedInstance")
        exists = bool(instance.instance_id)
        ready = instance.status == "READY"
        checks = (
            ValidationCheck(
                name="instance_exists",
                status="PASS" if exists else "FAIL",
                expected=True,
                actual=exists,
                message="instance metadata is present" if exists else "instance ID is missing",
            ),
            ValidationCheck(
                name="instance_status_ready",
                status="PASS" if ready else "FAIL",
                expected="READY",
                actual=instance.status,
                message="instance is READY" if ready else "instance is not READY",
            ),
        )
        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        return ValidationReport(
            benchmark_id=instance.benchmark_id,
            instance_id=instance.instance_id,
            status=status,
            checks=checks,
            metadata={"validator": self.__class__.__name__},
        )


register_validator("example-validator", ExampleValidator)
