"""The lifecycle boundary implemented by a benchmark adapter.

Adapters are deliberately orchestration-free at this layer. A concrete
benchmark owns source formats and database integration; the framework relies
on these six stage boundaries.
"""
from abc import ABC, abstractmethod
from typing import Any


class BenchmarkAdapter(ABC):
    """Abstract fetch-to-truth contract for one benchmark definition.

    Each stage returns an implementation-defined value consumed by the next
    stage. The base methods do no I/O and fail when called directly.
    """

    @abstractmethod
    def fetch(self) -> Any:
        """Acquire declared source material into immutable raw artifacts."""
        raise NotImplementedError

    @abstractmethod
    def prepare(self) -> Any:
        """Transform raw material into prepared artifacts deterministically."""
        raise NotImplementedError

    @abstractmethod
    def load(self) -> Any:
        """Load prepared artifacts into an experiment-ready instance."""
        raise NotImplementedError

    @abstractmethod
    def validate(self) -> Any:
        """Validate the loaded instance and its declared provenance."""
        raise NotImplementedError

    @abstractmethod
    def normalize_workload(self) -> Any:
        """Normalize workload inputs without changing recorded meaning."""
        raise NotImplementedError

    @abstractmethod
    def collect_truth(self) -> Any:
        """Collect truth artifacts from a validated instance."""
        raise NotImplementedError
