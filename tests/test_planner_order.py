from __future__ import annotations

import hashlib

from pgextstats_benchmarks.postgres.configuration_provider import (
    PLANNER_ORDER_CONTRACT,
    PostgreSQLStatisticsConfigurationProvider,
)
from pgextstats_benchmarks.postgres.instance import PostgresInstance
from pgextstats_benchmarks.statistics_configuration import StatisticsConfiguration
from pgextstats_benchmarks.statistics_repository import CandidatePayloadState, StatisticsRepositoryArtifact


SOURCE = {
    "repository": "https://github.com/1951123/postgresql-pgextadv",
    "source_commit": "6d7f5c9cd6cf1b0f73e84a4bacc45a31d1cb0cd6",
    "upstream_base_commit": "0d1c00c624fa7367d4a895f44381887757289682",
    "server_version": "PostgreSQL 16.14",
    "binary_sha256": "4" * 64,
}


class Target:
    database = "pgextbench_order"

    def __init__(self):
        self.registered = []
        self.activations = []

    def connect(self):
        return self

    def close(self):
        return None

    def hypothetical_reset(self):
        return None

    def relation_oid(self, relation):
        return 11

    def table_columns(self, table):
        return ["a", "b"]

    def hypothetical_register_definition(self, candidate_id, relation_oid, kind, keys, payload):
        oid = 200 + len(self.registered)
        self.registered.append((candidate_id, oid))
        return oid

    def hypothetical_activate(self, oids):
        self.activations.append(tuple(oids))
        return list(oids)


class Root:
    def __init__(self):
        self.target = Target()

    def for_database(self, database):
        return self.target

    def close(self):
        return None


def repository(tmp_path):
    payload_dir = tmp_path / "example" / "artifacts" / "order-v1" / "payloads"
    payload_dir.mkdir(parents=True)
    states = []
    for candidate_id, kind in (("a-fd", "fd"), ("z-mcv", "mcv")):
        payload = candidate_id.encode()
        (payload_dir / f"{candidate_id}.{kind}.bin").write_bytes(payload)
        states.append(CandidatePayloadState(
            candidate_id, kind, ("a", "b"), "PRESENT", hashlib.sha256(payload).hexdigest(),
            native_metadata={},
        ))
    return StatisticsRepositoryArtifact.create(
        artifact_id="order-v1", benchmark_id="example", relation_identity="public.fixture",
        sample_artifact_id="sample-v1", sample_payload_sha256="a" * 64,
        candidate_catalog={"catalog_id": "catalog-v1", "catalog_sha256": "b" * 64, "candidate_count": 2},
        postgres_source=SOURCE, statistics_target={"requested": 100, "effective": 100},
        ordinary_statistics_fingerprint="c" * 64, candidate_states=tuple(states),
        repository_digest="0" * 64, lineage={"sample_artifact_id": "sample-v1"},
    )


def test_configuration_membership_is_order_independent(tmp_path):
    repo = repository(tmp_path)
    first = StatisticsConfiguration("a", repo.artifact_id, repo.repository_digest, ("a-fd", "z-mcv"), repo.relation_identity)
    second = StatisticsConfiguration("a", repo.artifact_id, repo.repository_digest, ("z-mcv", "a-fd"), repo.relation_identity)
    assert first == second
    assert first.configuration_digest == second.configuration_digest


def test_provider_resolves_canonical_planner_order_for_permutations(tmp_path):
    repo = repository(tmp_path)
    root = Root()
    provider = PostgreSQLStatisticsConfigurationProvider(root)
    provider.register_repository(PostgresInstance("pgextbench_order", "pgextbench_order", "READY"), repo, root=tmp_path)
    assert provider.canonical_planner_order(("a-fd", "z-mcv")) == ("z-mcv", "a-fd")
    assert provider.canonical_planner_order(("z-mcv", "a-fd")) == ("z-mcv", "a-fd")
    configuration = StatisticsConfiguration("a", repo.artifact_id, repo.repository_digest, ("a-fd", "z-mcv"), repo.relation_identity, metadata={"planner_order_contract": PLANNER_ORDER_CONTRACT})
    provider.activate(configuration)
    assert root.target.activations[-1] == (201, 200)
    provider.close()
