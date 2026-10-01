import pytest

from pgextstats_benchmarks.artifacts import Artifact
from pgextstats_benchmarks.example_loader import ExampleMemoryLoader
from pgextstats_benchmarks.instances import LoadedInstance
from pgextstats_benchmarks.loader_registry import get_loader, list_loaders
from pgextstats_benchmarks.loaders import DatabaseLoader


def test_loader_registration_and_lookup():
    assert "example-memory" in list_loaders()
    assert get_loader("example-memory") is ExampleMemoryLoader
    with pytest.raises(ValueError, match="No loader"):
        get_loader("missing")


def test_database_loader_is_abstract():
    with pytest.raises(TypeError):
        DatabaseLoader()


def test_instance_serialization():
    instance = LoadedInstance(
        instance_id="example-memory-v1",
        benchmark_id="example",
        loader_type="ExampleMemoryLoader",
        status="READY",
        metadata={"artifact_ids": ["example-prepared-v1"]},
    )
    assert LoadedInstance.from_dict(instance.to_dict()) == instance


def test_example_memory_loader_lifecycle():
    loader = ExampleMemoryLoader()
    instance = loader.create_instance()
    assert instance.instance_id == "example-memory-v1"
    artifact = Artifact(id="example-prepared-v1", type="prepared_dataset")
    loaded = loader.load_artifact(instance, artifact)
    assert loaded.metadata["artifact_ids"] == ["example-prepared-v1"]
    one_step = loader.load_artifact(artifact)
    assert one_step.instance_id == "example-memory-v1"
    assert one_step.metadata["artifact_ids"] == ["example-prepared-v1"]
    assert loader.validate_instance(loaded)["status"] == "PASS"
    assert loader.destroy_instance(loaded)["status"] == "PASS"
