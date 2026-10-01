import json
import pytest
from pgextstats_benchmarks.artifacts import Artifact
from pgextstats_benchmarks.lineage import ArtifactLineage, Lineage

DIGEST = "a" * 64


def test_lineage_roundtrip():
    raw = Artifact(
        id="raw_dmv_csv", type="raw_dataset", digest=DIGEST, created_by="external-source"
    )
    prepared = Artifact(
        id="prepared_dmv_csv",
        type="prepared_dataset",
        parent_artifacts=("raw_dmv_csv",),
        digest="b" * 64,
        created_by="prepare-dmv",
    )
    lineage = ArtifactLineage((raw, prepared))
    assert isinstance(lineage, Lineage)
    restored = ArtifactLineage.from_dict(json.loads(lineage.to_json()))
    assert restored == lineage
    assert restored.to_dict()["artifacts"][1]["parent_artifacts"] == ["raw_dmv_csv"]


def test_lineage_rejects_unknown_parent_and_duplicate_id():
    with pytest.raises(ValueError, match="unknown parent"):
        ArtifactLineage((Artifact("prepared", "prepared_dataset", parent_artifacts=("missing",)),))
    raw = Artifact("raw", "raw_dataset")
    with pytest.raises(ValueError, match="unique"):
        ArtifactLineage((raw, raw))
