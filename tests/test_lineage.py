import json
import pytest
from pgextstats_benchmarks.lineage import Artifact, ArtifactLineage

DIGEST = "a" * 64


def test_lineage_roundtrip():
    raw = Artifact("raw_dmv_csv", "raw", (), "external-source", None, DIGEST)
    prepared = Artifact("prepared_dmv_csv", "prepared", ("raw_dmv_csv",),
                        "prepare-dmv", "b" * 40, "b" * 64)
    lineage = ArtifactLineage((raw, prepared))
    restored = ArtifactLineage.from_dict(json.loads(lineage.to_json()))
    assert restored == lineage
    assert restored.to_dict()["artifacts"][1]["parent_artifacts"] == ["raw_dmv_csv"]


def test_lineage_rejects_unknown_parent_and_duplicate_id():
    with pytest.raises(ValueError, match="unknown parent"):
        ArtifactLineage((Artifact("prepared", "prepared", ("missing",),
                                  "tool", None, DIGEST),))
    raw = Artifact("raw", "raw", (), "tool", None, DIGEST)
    with pytest.raises(ValueError, match="unique"):
        ArtifactLineage((raw, raw))
