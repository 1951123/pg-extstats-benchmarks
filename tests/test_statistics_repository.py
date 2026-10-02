from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pgextstats_benchmarks.candidate_catalog import CandidateCatalog
from pgextstats_benchmarks.postgres.instance import PostgresInstance
from pgextstats_benchmarks.postgres.statistics_provider import PostgreSQLStatisticsRepositoryProvider
from pgextstats_benchmarks.sample_artifacts import SampleArtifact
from pgextstats_benchmarks.statistics_repository import CandidatePayloadState, StatisticsRepositoryArtifact
from pgextstats_benchmarks.statistics_repository_validator import StatisticsRepositoryValidator


SOURCE = {
    "repository": "https://github.com/1951123/postgresql-pgextadv",
    "source_commit": "7e992ab6438fef2f8eb98c7a9ed30c9f1c816ce7",
    "upstream_base_commit": "0d1c00c624fa7367d4a895f44381887757289682",
    "server_version": "PostgreSQL 16.14",
    "binary_sha256": "4" * 64,
}


def make_catalog(path: Path | None = None) -> CandidateCatalog:
    value = {
        "catalog_id": "fixture-catalog-v1",
        "relation_identity": "public.fixture",
        "statistics_target": 100,
        "candidates": [
            {"candidate_id": "fd-b", "mechanism": "fd", "attributes": ["a", "b"]},
            {"candidate_id": "mcv-a", "mechanism": "mcv", "attributes": ["a", "b"]},
        ],
    }
    if path is None:
        return CandidateCatalog.from_mapping(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return CandidateCatalog.from_file(path)


def make_sample(root: Path) -> SampleArtifact:
    directory = root / "fixture" / "artifacts" / "fixture-sample-v1"
    directory.mkdir(parents=True)
    payload = directory / "sample.bin"
    payload.write_bytes(b"PGEXTSC1-fixture")
    return SampleArtifact(
        artifact_id="fixture-sample-v1", benchmark_id="fixture",
        relation_identity="public.fixture", parent_data_artifact_id="fixture-data-v1",
        loaded_instance_id="pgextbench_fixture_1", format="PGEXTSC1", format_version=1,
        payload_relative_path="fixture/artifacts/fixture-sample-v1/sample.bin",
        payload_sha256=hashlib.sha256(payload.read_bytes()).hexdigest(), sample_tuple_count=2,
        estimated_total_rows=2, postgres_source=SOURCE,
        acquisition={"mechanism": "postgres_analyze_sample_cache"}, schema_fingerprint="f" * 64,
        lineage={"parent_artifact_ids": ["fixture-data-v1"]},
    )


def make_repository(catalog: CandidateCatalog) -> StatisticsRepositoryArtifact:
    states = tuple(
        CandidatePayloadState(c.candidate_id, c.kind, c.columns, "ABSENT_NATIVE", None)
        for c in catalog.candidates
    )
    return StatisticsRepositoryArtifact.create(
        artifact_id="fixture-repository-v1", benchmark_id="fixture",
        relation_identity=catalog.relation_identity, sample_artifact_id="fixture-sample-v1",
        sample_payload_sha256="a" * 64,
        candidate_catalog={"catalog_id": catalog.catalog_id, "catalog_sha256": catalog.catalog_sha256, "candidate_count": catalog.candidate_count},
        postgres_source=SOURCE, statistics_target={"requested": 100, "effective": 100, "scope": "global"},
        ordinary_statistics_fingerprint="b" * 64, candidate_states=states,
        repository_digest="0" * 64,
        lineage={"parent_data_artifact_id": "fixture-data-v1", "sample_artifact_id": "fixture-sample-v1"},
    )


def test_catalog_ordering_and_digest(tmp_path):
    catalog = make_catalog(tmp_path / "catalog.json")
    assert [item.candidate_id for item in catalog.candidates] == ["fd-b", "mcv-a"]
    assert len(catalog.catalog_sha256) == 64
    with pytest.raises(ValueError, match="unique"):
        CandidateCatalog.from_mapping({**catalog.canonical_dict(), "candidates": [catalog.candidates[0].to_dict()] * 2})


def test_repository_round_trip_and_state_semantics(tmp_path):
    catalog = make_catalog()
    artifact = make_repository(catalog)
    assert StatisticsRepositoryArtifact.from_dict(json.loads(artifact.to_json())) == artifact
    assert artifact.repository_digest == artifact.compute_repository_digest()
    with pytest.raises(ValueError, match="ABSENT_NATIVE"):
        CandidatePayloadState("x", "mcv", ("a", "b"), "ABSENT_NATIVE", "a" * 64)
    present = CandidatePayloadState("x", "mcv", ("a", "b"), "PRESENT", "a" * 64)
    assert present.state == "PRESENT"


def test_repository_validator_rejects_catalog_mismatch():
    catalog = make_catalog()
    artifact = make_repository(catalog)
    other = make_catalog()
    object.__setattr__(other, "catalog_id", "other")
    report = StatisticsRepositoryValidator().validate(artifact, candidate_catalog=other)
    assert report.status == "FAIL"


def test_repository_validator_reports_corrupted_digest(tmp_path):
    artifact = make_repository(make_catalog())
    object.__setattr__(artifact, "repository_digest", "0" * 64)
    report = StatisticsRepositoryValidator().validate(artifact, root=tmp_path)
    assert report.status == "FAIL"
    assert any(check.name == "repository_digest" and check.status == "FAIL" for check in report.checks)


class FakeTarget:
    def __init__(self):
        self.created = []
        self.dropped = []
        self.analyze_count = 0
        self.config = {}

    def connect(self): return self
    def close(self): pass
    def set_default_statistics_target(self, value): self.config["target"] = value
    def statistics_object(self, schema, name):
        if name not in self.created: return None
        return (100 + len(self.created), 42, "{m}" if "mcv" in name else "{f}", name)
    def create_statistics(self, schema, name, kind, columns, relation): self.created.append(name)
    def set_statistics_target(self, schema, name, target): self.config[name] = target
    def analyze(self, relation): self.analyze_count += 1
    def ordinary_statistics(self, relation): return [("a", 0.0, 4, -1.0, None, None, None, 1.0)]
    def native_statistics_payload(self, schema, name, kind): return (b"payload-" + kind.encode(), 1, 42, "{m}")
    def drop_statistics(self, schema, name): self.dropped.append(name)


class FakeConnection:
    def __init__(self): self.target = FakeTarget()
    def for_database(self, database): return self.target


class FakeSampleProvider:
    def __init__(self): self.imports = 0; self.ends = 0
    def begin_sample_import(self, target, artifact, relation, root): self.imports += 1
    def end_sample_import(self, target): self.ends += 1


def test_provider_one_import_one_analyze_and_cleanup(tmp_path):
    catalog = make_catalog(tmp_path / "catalog.json")
    sample = make_sample(tmp_path)
    connection = FakeConnection(); sample_provider = FakeSampleProvider()
    provider = PostgreSQLStatisticsRepositoryProvider(connection, sample_provider)
    instance = PostgresInstance("pgextbench_fixture_1", "pgextbench_fixture_1", "LOADED")
    result = provider.acquire_repository(instance, sample, catalog, benchmark_id="fixture", root=tmp_path)
    assert result["sample_import_count"] == 1
    assert result["analyze_count"] == 1
    assert result["present_count"] == 2
    assert connection.target.analyze_count == 1
    assert sample_provider.imports == sample_provider.ends == 1
    assert len(connection.target.dropped) == 2
