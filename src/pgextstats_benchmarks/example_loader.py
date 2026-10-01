"""In-memory loader used to exercise the loader contract."""
from dataclasses import replace
from typing import Any

from .artifacts import Artifact
from .instances import LoadedInstance
from .loader_registry import register_loader
from .loaders import DatabaseLoader


class ExampleMemoryLoader(DatabaseLoader):
    """A metadata-only loader with no files, processes, or database calls."""

    def create_instance(self, benchmark_id: str = "example") -> LoadedInstance:
        return LoadedInstance(
            instance_id=f"{benchmark_id}-memory-v1",
            benchmark_id=benchmark_id,
            loader_type=self.__class__.__name__,
            status="READY",
            metadata={"artifact_ids": [], "materialization": "memory-only"},
        )

    def load_artifact(
        self,
        instance: LoadedInstance | Artifact,
        artifact: Artifact | None = None,
    ) -> LoadedInstance:
        if artifact is None:
            artifact = instance if isinstance(instance, Artifact) else None
            instance = self.create_instance()
        if not isinstance(instance, LoadedInstance):
            raise TypeError("instance must be a LoadedInstance")
        if not isinstance(artifact, Artifact):
            raise TypeError("artifact must be an Artifact")
        artifact_ids = list(instance.metadata.get("artifact_ids", ()))
        if artifact.id not in artifact_ids:
            artifact_ids.append(artifact.id)
        metadata = dict(instance.metadata)
        metadata["artifact_ids"] = artifact_ids
        return replace(instance, status="READY", metadata=metadata)

    def validate_instance(self, instance: LoadedInstance) -> dict[str, Any]:
        if not isinstance(instance, LoadedInstance):
            raise TypeError("instance must be a LoadedInstance")
        return {
            "status": "PASS",
            "message": "example memory instance validated",
            "instance": instance.to_dict(),
        }

    def destroy_instance(self, instance: LoadedInstance) -> dict[str, Any]:
        if not isinstance(instance, LoadedInstance):
            raise TypeError("instance must be a LoadedInstance")
        return {
            "status": "PASS",
            "message": "example memory instance destroyed",
            "instance_id": instance.instance_id,
        }


register_loader("example-memory", ExampleMemoryLoader)
