import hashlib
import json
from pathlib import Path

import pytest

from pgextstats_benchmarks.sample_artifacts import SampleArtifact
from pgextstats_benchmarks.sample_storage import (
    allocate_sample_artifact_dir,
    load_sample_manifest,
    verify_sample_artifact,
    write_sample_manifest,
)
from pgextstats_benchmarks.sample_validator import SampleArtifactValidator
from pgextstats_benchmarks.postgres.instance import PostgresInstance
from pgextstats_benchmarks.postgres.sample_provider import PostgreSQLAnalyzeSampleProvider


def make_artifact(root: Path) -> SampleArtifact:
    directory = allocate_sample_artifact_dir("example", "example-sample-v1", root)
    payload = directory / "sample.bin"
    payload.write_bytes(b"PGEXTSC1-fixture")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    artifact = SampleArtifact(
        artifact_id="example-sample-v1",
        benchmark_id="example",
        relation_identity="public.example_table",
        parent_data_artifact_id="example-prepared-v1",
        loaded_instance_id="pgextbench_example_1",
        format="PGEXTSC1",
        format_version=1,
        payload_relative_path="example/artifacts/example-sample-v1/sample.bin",
        payload_sha256=digest,
        sample_tuple_count=2,
        estimated_total_rows=2,
        postgres_source={
            "repository": "https://github.com/1951123/postgresql-pgextadv",
            "source_commit": "7e992ab6438fef2f8eb98c7a9ed30c9f1c816ce7",
            "upstream_base_commit": "0d1c00c624fa7367d4a895f44381887757289682",
            "server_version": "PostgreSQL 16.14",
        },
        acquisition={
            "mechanism": "postgres_analyze_sample_cache",
            "source_relation_identity": "public.example_table",
        },
        schema_fingerprint="a" * 64,
        lineage={"parent_artifact_ids": ["example-prepared-v1"]},
    )
    write_sample_manifest(artifact, root)
    return artifact


def test_sample_artifact_round_trip_and_opaque_payload(tmp_path):
    artifact = make_artifact(tmp_path)
    restored = SampleArtifact.from_dict(json.loads(artifact.to_json()))
    assert restored == artifact
    assert load_sample_manifest("example", "example-sample-v1", tmp_path) == artifact
    assert verify_sample_artifact(artifact, tmp_path).read_bytes().startswith(b"PGEXTSC1")
    assert SampleArtifactValidator().validate(artifact, tmp_path).status == "PASS"


def test_sample_artifact_rejects_oid_identity_and_bad_payload(tmp_path):
    with pytest.raises(ValueError, match="logical"):
        SampleArtifact(
            artifact_id="x", benchmark_id="b", relation_identity="oid:42",
            parent_data_artifact_id="p", loaded_instance_id="i", format="PGEXTSC1",
            format_version=1, payload_relative_path="b/artifacts/x/sample.bin",
            payload_sha256="0" * 64, sample_tuple_count=0, estimated_total_rows=0,
            postgres_source={"repository": "r", "source_commit": "c", "upstream_base_commit": "u", "server_version": "v"},
            acquisition={"mechanism": "postgres_analyze_sample_cache"}, schema_fingerprint="f",
        )
    artifact = make_artifact(tmp_path)
    payload = verify_sample_artifact(artifact, tmp_path)
    payload.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        verify_sample_artifact(artifact, tmp_path)


def test_sample_storage_rejects_unsafe_root_and_path(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        allocate_sample_artifact_dir("example", "sample", link / "new")


class FakeTarget:
    def __init__(self):
        self.config = {}
        self.analyzed = []
        self.closed = False

    def connect(self):
        return self

    def execute(self, query, params=None):
        if "current_setting" in str(query):
            return [("", "")]
        return []

    def server_version(self):
        return "PostgreSQL 16.14 (pgextadv)"

    def relation_metadata(self, relation):
        return [(42, "public", "example_table", 1, "id", 23, -1, 0, False)]

    def set_config(self, name, value):
        self.config[name] = value

    def analyze(self, relation):
        self.analyzed.append(relation)
        path = self.config.get("pgextadv.analyze_sample_export")
        if path:
            Path(path).write_bytes(b"PGEXTSC1-fixture")

    def notices(self):
        return ['NOTICE:  "example_table": scanned 1 of 1 pages, 2 rows in sample, 2 estimated total rows']

    def close(self):
        self.closed = True


class FakeConnection:
    host = "localhost"
    port = 55437

    def __init__(self):
        self.target = FakeTarget()

    def for_database(self, database):
        return self.target


def test_provider_capture_and_replay(tmp_path):
    connection = FakeConnection()
    provider = PostgreSQLAnalyzeSampleProvider(connection)
    instance = PostgresInstance("pgextbench_example_1", "pgextbench_example_1", "LOADED")
    result = provider.capture_sample(
        instance, "public.example_table", benchmark_id="example",
        parent_data_artifact_id="example-prepared-v1", root=tmp_path,
    )
    artifact = result["artifact"]
    assert result["status"] == "PASS"
    assert artifact.sample_tuple_count == 2
    assert connection.target.analyzed == ["public.example_table"]
    replay = provider.replay_sample(instance, artifact, root=tmp_path)
    assert replay.status == "PASS"
    assert connection.target.config["pgextadv.analyze_sample_export"] == ""
    assert connection.target.config["pgextadv.analyze_sample_import"] == ""
