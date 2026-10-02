"""Native PostgreSQL planner-estimate collection over hypothetical state."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..estimate import EstimateArtifact, QueryEstimate, workload_digest
from ..estimate_storage import allocate_estimate_artifact_dir, write_estimate_artifact
from ..statistics_configuration import StatisticsConfiguration
from ..statistics_repository import StatisticsRepositoryArtifact
from ..workload_executor import Workload
from .configuration_provider import PostgreSQLStatisticsConfigurationProvider
from .instance import PostgresInstance


_UNSUPPORTED = re.compile(r"\b(join|union|intersect|except)\b", re.IGNORECASE)


def _target_relation(relation_identity: str) -> str:
    parts = relation_identity.split(".")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("relation identity must be schema.relation")
    return parts[1]


def extract_plan_rows(plan_json: Any, relation_identity: str) -> float:
    if not isinstance(plan_json, list) or len(plan_json) != 1 or not isinstance(plan_json[0], dict) or "Plan" not in plan_json[0]:
        raise ValueError("unexpected EXPLAIN JSON shape")
    matches: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            raise ValueError("unexpected plan node")
        if node.get("Relation Name") == _target_relation(relation_identity):
            matches.append(node)
        for child in node.get("Plans", ()):
            visit(child)

    visit(plan_json[0]["Plan"])
    if len(matches) != 1:
        raise ValueError(f"target relation {relation_identity!r} matched {len(matches)} plan nodes")
    estimate = matches[0].get("Plan Rows")
    if not isinstance(estimate, (int, float)) or isinstance(estimate, bool):
        raise ValueError("target plan node has no numeric Plan Rows")
    if estimate < 0:
        raise ValueError("target Plan Rows is negative")
    return float(estimate)


class PostgreSQLEstimateProvider:
    """Collect Plan Rows without ANALYZE or physical statistics changes."""

    def __init__(self, configuration_provider: PostgreSQLStatisticsConfigurationProvider | None = None) -> None:
        self.configuration_provider = configuration_provider or PostgreSQLStatisticsConfigurationProvider()
        self.explain_calls = 0

    @staticmethod
    def _query_status(query_sql: str) -> str | None:
        stripped = query_sql.strip()
        if not stripped.upper().startswith("SELECT"):
            return "query is not a SELECT"
        if _UNSUPPORTED.search(stripped):
            return "joins and set operations are outside the supported scope"
        # A comma-separated FROM list is a join even when JOIN syntax is absent.
        from_match = re.search(r"\bFROM\b(.*?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", stripped, re.IGNORECASE | re.DOTALL)
        if from_match and "," in from_match.group(1):
            return "multi-relation FROM lists are outside the supported scope"
        return None

    def collect(
        self,
        instance: PostgresInstance,
        workload: Workload,
        repository: StatisticsRepositoryArtifact,
        configuration: StatisticsConfiguration,
        *,
        benchmark_id: str,
        root: Path | None = None,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(workload, Workload):
            raise TypeError("workload must be a Workload")
        if workload.query_count == 0:
            raise ValueError("workload must contain at least one query")
        if repository.benchmark_id != benchmark_id:
            raise ValueError("repository benchmark does not match estimate benchmark")
        configuration.validate_against(repository)
        artifact_id = artifact_id or f"{benchmark_id}-estimate-{configuration.configuration_id}"
        provider = self.configuration_provider
        target = provider.bind_instance(instance)
        registered = False
        results: list[QueryEstimate] = []
        try:
            registration = provider.register_repository(instance, repository, root=root)
            registered = True
            provider.reset_configuration()
            provider.activate(configuration)
            for query in workload.queries:
                unsupported = self._query_status(query.sql)
                if unsupported is not None:
                    results.append(QueryEstimate(query.query_id, "UNSUPPORTED", metadata={"reason": unsupported}))
                    continue
                try:
                    plan = target.explain_json(query.sql)
                    self.explain_calls += 1
                    rows = extract_plan_rows(plan, repository.relation_identity)
                    results.append(QueryEstimate(query.query_id, "PASS", estimated_rows=rows))
                except Exception as exc:
                    results.append(QueryEstimate(query.query_id, "ERROR", metadata={"error": str(exc)}))
            artifact = EstimateArtifact.create(
                artifact_id=artifact_id,
                benchmark_id=benchmark_id,
                workload_id=workload.workload_id,
                workload_digest=workload_digest(workload),
                repository_artifact_id=repository.artifact_id,
                repository_digest=repository.repository_digest,
                configuration_id=configuration.configuration_id,
                configuration_digest=configuration.configuration_digest,
                relation_identity=repository.relation_identity,
                postgres_source={
                    **dict(repository.postgres_source),
                    "version": repository.postgres_source.get("version", repository.postgres_source.get("server_version")),
                },
                query_estimates=tuple(results),
                query_count=len(results),
                successful_count=sum(item.status == "PASS" for item in results),
                failed_count=sum(item.status == "ERROR" for item in results),
                estimate_digest="0" * 64,
                lineage={
                    "workload_id": workload.workload_id,
                    "repository_artifact_id": repository.artifact_id,
                    "configuration_id": configuration.configuration_id,
                },
                metadata={"registration_calls": provider.registration_calls, "activation_calls": provider.activation_calls, "explain_calls": self.explain_calls, "repository_registration_reused": not registration["registered"]},
            )
            allocate_estimate_artifact_dir(benchmark_id, artifact_id, root)
            manifest = write_estimate_artifact(artifact, root)
            return {
                "status": artifact.status,
                "message": "PostgreSQL estimate collection completed",
                "artifact": artifact,
                "manifest_path": manifest,
                "registration": registration,
                "query_count": artifact.query_count,
                "successful_count": artifact.successful_count,
                "unsupported_count": sum(item.status == "UNSUPPORTED" for item in results),
                "failed_count": artifact.failed_count,
            }
        finally:
            if registered:
                provider.reset_configuration()

    def close(self) -> None:
        self.configuration_provider.close()


__all__ = ["PostgreSQLEstimateProvider", "extract_plan_rows"]
