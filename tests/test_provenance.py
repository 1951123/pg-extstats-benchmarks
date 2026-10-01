from datetime import datetime, timezone
import json
import pytest
from pgextstats_benchmarks.provenance import ArtifactProvenance


def record(**changes):
    values = dict(source_url="https://example.invalid/fixture",
                  download_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                  sha256="a" * 64, file_size=42)
    values.update(changes)
    return ArtifactProvenance(**values)


def test_roundtrip():
    item = record(row_count=2, schema_digest="b" * 64,
                  transformation_version="v1", prepared_artifact_digest="c" * 64,
                  loader_version="v1")
    assert ArtifactProvenance.from_dict(json.loads(item.to_json())) == item


@pytest.mark.parametrize("changes", [dict(sha256="bad"), dict(file_size=-1),
    dict(row_count=-1), dict(row_count=True), dict(source_url=""),
    dict(download_timestamp=datetime(2026, 1, 1)), dict(schema_digest="bad")])
def test_invalid_metadata(changes):
    with pytest.raises(ValueError):
        record(**changes)
