"""DBMS-independent loader contract.

Concrete loaders may materialize prepared artifacts in a managed system, but
the framework does not prescribe a database, connection API, or cleanup
mechanism. ``destroy_instance`` is scoped to the managed instance supplied by
the caller; it must never perform arbitrary filesystem deletion.
"""
from abc import ABC, abstractmethod
from typing import Any

from .artifacts import Artifact
from .instances import LoadedInstance


class DatabaseLoader(ABC):
    """Abstract lifecycle for materializing prepared benchmark artifacts."""

    @abstractmethod
    def create_instance(self, benchmark_id: str = "example") -> LoadedInstance:
        """Create metadata for one managed benchmark instance."""
        raise NotImplementedError

    @abstractmethod
    def load_artifact(
        self,
        instance: LoadedInstance | Artifact,
        artifact: Artifact | None = None,
    ) -> LoadedInstance:
        """Load one prepared artifact into the managed instance.

        Implementations may accept an artifact alone and create their default
        managed instance, or accept an explicit instance and artifact pair.
        """
        raise NotImplementedError

    @abstractmethod
    def validate_instance(self, instance: LoadedInstance) -> dict[str, Any]:
        """Validate the managed instance and return a status mapping."""
        raise NotImplementedError

    @abstractmethod
    def destroy_instance(self, instance: LoadedInstance) -> dict[str, Any]:
        """Destroy only the managed instance represented by ``instance``."""
        raise NotImplementedError
