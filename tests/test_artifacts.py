from pgextstats_benchmarks.artifacts import Artifact
from pgextstats_benchmarks.lineage import ArtifactLineage


def test_artifact_serialization_is_deterministic():
    artifact = Artifact(
        id="example-raw-v1",
        type="raw_dataset",
        path="external/example.csv",
        digest="abc123",
        metadata={"rows": 3, "source": "toy"},
        created_at="2026-10-01T00:00:00+00:00",
        created_by="example-fetch",
        creation_info={"version": "v1"},
    )
    restored = Artifact.from_dict(artifact.to_dict())
    assert restored == artifact
    assert artifact.to_json() == artifact.to_json()


def test_lineage_serializes_managed_artifacts():
    raw = Artifact(id="example-raw-v1", type="raw_dataset")
    prepared = Artifact(
        id="example-prepared-v1",
        type="prepared_dataset",
        parent_artifacts=("example-raw-v1",),
        created_by="example-prepare",
    )
    lineage = ArtifactLineage((raw, prepared))
    restored = ArtifactLineage.from_dict(lineage.to_dict())
    assert restored == lineage
    assert restored.artifacts[1].parent_artifacts == ("example-raw-v1",)
