from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pgextstats_benchmarks.estimate import EstimateArtifact, QueryEstimate, workload_digest
from pgextstats_benchmarks.postgres.configuration_provider import PostgreSQLStatisticsConfigurationProvider
from pgextstats_benchmarks.postgres.estimate_provider import PostgreSQLEstimateProvider, extract_plan_rows
from pgextstats_benchmarks.postgres.instance import PostgresInstance
from pgextstats_benchmarks.statistics_configuration import StatisticsConfiguration
from pgextstats_benchmarks.statistics_configuration_validator import StatisticsConfigurationValidator
from pgextstats_benchmarks.statistics_repository import CandidatePayloadState, StatisticsRepositoryArtifact
from pgextstats_benchmarks.workload_executor import Query, Workload


SOURCE = {
    "repository": "https://github.com/1951123/postgresql-pgextadv",
    "source_commit": "7e992ab6438fef2f8eb98c7a9ed30c9f1c816ce7",
    "upstream_base_commit": "0d1c00c624fa7367d4a895f44381887757289682",
    "server_version": "PostgreSQL 16.14",
    "binary_sha256": "4" * 64,
}


def make_repository(root: Path) -> StatisticsRepositoryArtifact:
    payload_dir = root / "example" / "artifacts" / "repo-v1" / "payloads"
    payload_dir.mkdir(parents=True)
    states = []
    for index, (candidate_id, kind) in enumerate(
        (("c001", "mcv"), ("c002", "mcv"), ("c003", "fd"), ("c004", "fd"))
    ):
        payload = f"payload-{candidate_id}".encode()
        (payload_dir / f"{candidate_id}.{kind}.bin").write_bytes(payload)
        states.append(CandidatePayloadState(
            candidate_id, kind, ("a", "b"), "PRESENT", hashlib.sha256(payload).hexdigest(),
            native_metadata={"statistics_name": f"pgextbench_stat_{candidate_id}", "backend_oid_diagnostic": 100 + index, "relation_oid_diagnostic": 11, "stxkind": "['m']" if kind == "mcv" else "['f']"},
        ))
    return StatisticsRepositoryArtifact.create(
        artifact_id="repo-v1", benchmark_id="example", relation_identity="public.fixture",
        sample_artifact_id="sample-v1", sample_payload_sha256="a" * 64,
        candidate_catalog={"catalog_id": "catalog-v1", "catalog_sha256": "b" * 64, "candidate_count": 4},
        postgres_source=SOURCE, statistics_target={"requested": 100, "effective": 100},
        ordinary_statistics_fingerprint="c" * 64, candidate_states=tuple(states),
        repository_digest="0" * 64, lineage={"sample_artifact_id": "sample-v1"},
    )


def make_configuration(repository: StatisticsRepositoryArtifact, selected=()) -> StatisticsConfiguration:
    return StatisticsConfiguration(
        configuration_id="config-" + ("empty" if not selected else "subset"),
        repository_artifact_id=repository.artifact_id,
        repository_digest=repository.repository_digest,
        selected_candidate_ids=tuple(selected),
        relation_identity=repository.relation_identity,
        lineage={"repository_artifact_id": repository.artifact_id},
    )


def test_configuration_round_trip_empty_full_and_validation(tmp_path):
    repository = make_repository(tmp_path)
    empty = make_configuration(repository)
    full = make_configuration(repository, ["c004", "c002", "c003", "c001"])
    assert empty.selected_candidate_ids == ()
    assert full.selected_candidate_ids == ("c001", "c002", "c003", "c004")
    assert StatisticsConfiguration.from_dict(json.loads(full.to_json())) == full
    assert StatisticsConfigurationValidator().validate(empty, repository).status == "PASS"
    assert StatisticsConfigurationValidator().validate(full, repository).status == "PASS"
    with pytest.raises(ValueError, match="unique"):
        make_configuration(repository, ["c001", "c001"])
    unknown = make_configuration(repository, ["missing"])
    assert StatisticsConfigurationValidator().validate(unknown, repository).status == "FAIL"


def test_configuration_rejects_absent_native(tmp_path):
    repository = make_repository(tmp_path)
    states = list(repository.candidate_states)
    states[0] = CandidatePayloadState("c001", "mcv", ("a", "b"), "ABSENT_NATIVE", None, native_metadata=states[0].native_metadata)
    repository = StatisticsRepositoryArtifact.create(
        artifact_id=repository.artifact_id, benchmark_id=repository.benchmark_id, relation_identity=repository.relation_identity,
        sample_artifact_id=repository.sample_artifact_id, sample_payload_sha256=repository.sample_payload_sha256,
        candidate_catalog=repository.candidate_catalog, postgres_source=repository.postgres_source,
        statistics_target=repository.statistics_target, ordinary_statistics_fingerprint=repository.ordinary_statistics_fingerprint,
        candidate_states=tuple(states), repository_digest="0" * 64, lineage=repository.lineage,
    )
    config = make_configuration(repository, ["c001"])
    assert StatisticsConfigurationValidator().validate(config, repository).status == "FAIL"


def test_estimate_artifact_round_trip_and_invalid_pass():
    result = QueryEstimate("q001", "PASS", estimated_rows=12)
    artifact = EstimateArtifact.create(
        artifact_id="estimate-v1", benchmark_id="example", workload_id="workload-v1",
        workload_digest="1" * 64, repository_artifact_id="repo-v1", repository_digest="2" * 64,
        configuration_id="config-v1", configuration_digest="3" * 64, relation_identity="public.fixture",
        postgres_source=SOURCE, query_estimates=(result,), query_count=1, successful_count=1, failed_count=0,
        estimate_digest="0" * 64, lineage={"configuration_id": "config-v1"},
    )
    assert EstimateArtifact.from_dict(json.loads(artifact.to_json())) == artifact
    assert artifact.estimate_digest == artifact.compute_estimate_digest()
    with pytest.raises(ValueError, match="estimated_rows"):
        QueryEstimate("q001", "PASS")


class FakeTarget:
    database = "pgextbench_example"

    def __init__(self):
        self.active = []
        self.registered = []
        self.calls = []

    def connect(self): return self
    def close(self): pass
    def hypothetical_reset(self): self.calls.append("reset")
    def relation_oid(self, relation): return 11
    def statistics_object(self, schema, name):
        candidate = name.rsplit("_", 1)[-1]
        oid = {"c001": 101, "c002": 102, "c003": 103, "c004": 104}[candidate]
        kind = "['m']" if candidate in {"c001", "c002"} else "['f']"
        return (oid, 11, kind, name)
    def hypothetical_register(self, oid, relation_oid, kind, payload): self.registered.append(oid)
    def hypothetical_register_absent(self, oid, relation_oid, kind): self.registered.append(oid)
    def hypothetical_activate(self, oids):
        self.calls.append(("activate", tuple(oids)))
        self.active = list(oids)
        return list(oids)
    def hypothetical_active(self): return list(self.active)
    def explain_json(self, query):
        self.calls.append(("explain", query))
        return [{"Plan": {"Node Type": "Seq Scan", "Relation Name": "fixture", "Plan Rows": 42}}]

    # These operations are intentionally absent from the estimate provider path.
    def analyze(self, relation): raise AssertionError("estimate collection must not ANALYZE")
    def create_statistics(self, *args): raise AssertionError("estimate collection must not CREATE STATISTICS")
    def drop_statistics(self, *args): raise AssertionError("estimate collection must not DROP STATISTICS")


class FakeRootConnection:
    def __init__(self): self.target = FakeTarget()
    def for_database(self, database): return self.target
    def close(self): pass


class CataloglessFakeTarget(FakeTarget):
    def table_columns(self, table):
        assert table == "fixture"
        return ["a", "b"]

    def statistics_object(self, schema, name):
        raise AssertionError("catalogless registration must not inspect pg_statistic_ext")

    def hypothetical_register_definition(self, candidate_id, relation_oid, kind, attribute_keys, payload):
        self.calls.append(("catalogless_register", candidate_id, kind, tuple(attribute_keys)))
        oid = 200 + len(self.registered)
        self.registered.append(oid)
        return oid

    def hypothetical_register_definition_absent(self, candidate_id, relation_oid, kind, attribute_keys):
        self.calls.append(("catalogless_register_absent", candidate_id, kind, tuple(attribute_keys)))
        oid = 200 + len(self.registered)
        self.registered.append(oid)
        return oid


class CataloglessFakeRootConnection:
    def __init__(self): self.target = CataloglessFakeTarget()
    def for_database(self, database): return self.target
    def close(self): pass


def test_catalogless_registration_does_not_require_physical_definitions(tmp_path):
    repository = make_repository(tmp_path)
    connection = CataloglessFakeRootConnection()
    provider = PostgreSQLStatisticsConfigurationProvider(connection)
    instance = PostgresInstance("pgextbench_example", "pgextbench_example", "READY")
    result = provider.register_repository(instance, repository, root=tmp_path)
    assert result["status"] == "PASS"
    assert result["catalogless"] is True
    assert provider.registration_calls == 4
    assert connection.target.calls[0] == "reset"
    assert [call[0] for call in connection.target.calls[1:]] == [
        "catalogless_register", "catalogless_register",
        "catalogless_register", "catalogless_register",
    ]


def test_estimate_provider_exact_subset_reuse_and_no_physical_operations(tmp_path):
    repository = make_repository(tmp_path)
    workload = Workload("workload-v1", (Query("q001", "SELECT * FROM public.fixture WHERE a = 1"), Query("q002", "SELECT * FROM public.fixture WHERE b = 1")))
    connection = FakeRootConnection()
    config_provider = PostgreSQLStatisticsConfigurationProvider(connection)
    provider = PostgreSQLEstimateProvider(config_provider)
    instance = PostgresInstance("pgextbench_example", "pgextbench_example", "READY")
    config_a = make_configuration(repository, ["c001", "c003"])
    config_b = make_configuration(repository, ["c002", "c004"])
    a1 = provider.collect(instance, workload, repository, config_a, benchmark_id="example", root=tmp_path, artifact_id="estimate-a1")
    b = provider.collect(instance, workload, repository, config_b, benchmark_id="example", root=tmp_path, artifact_id="estimate-b")
    a2 = provider.collect(instance, workload, repository, config_a, benchmark_id="example", root=tmp_path, artifact_id="estimate-a2")
    assert a1["status"] == b["status"] == a2["status"] == "PASS"
    assert a1["artifact"].estimate_digest == a2["artifact"].estimate_digest
    activation = [item for item in connection.target.calls if item[0] == "activate"]
    assert any(item[1] == (101, 103) for item in activation)
    assert any(item[1] == (102, 104) for item in activation)
    assert config_provider.registration_calls == 4
    assert not any(item == "analyze" for item in connection.target.calls)
    assert workload_digest(workload) == a1["artifact"].workload_digest


def test_plan_rows_and_unsupported_scope():
    plan = [{"Plan": {"Relation Name": "fixture", "Plan Rows": 7}}]
    assert extract_plan_rows(plan, "public.fixture") == 7.0
    assert PostgreSQLEstimateProvider._query_status("SELECT * FROM a JOIN b ON a.id=b.id")
