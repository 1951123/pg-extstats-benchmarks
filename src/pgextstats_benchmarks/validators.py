"""Common contract for benchmark-specific instance validators."""
from abc import ABC, abstractmethod

from .instances import LoadedInstance
from .validation import ValidationReport


class BenchmarkValidator(ABC):
    """Benchmark-specific correctness checks with a shared report format."""

    @abstractmethod
    def validate_instance(self, instance: LoadedInstance) -> ValidationReport:
        """Return a validation report for a loaded instance."""
        raise NotImplementedError
