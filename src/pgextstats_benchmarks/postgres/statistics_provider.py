"""One-ANALYZE native statistics repository acquisition."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..candidate_catalog import CandidateCatalog
from ..sample_artifacts import SampleArtifact
from ..statistics_repository import CandidatePayloadState, StatisticsRepositoryArtifact
from ..statistics_storage import allocate_repository_artifact_dir, write_repository_artifact
from .connection import PostgresConnection
from .instance import PostgresInstance
from .loader import validate_managed_database_name
from .sample_provider import PostgreSQLAnalyzeSampleProvider


MANAGED_STATISTICS_PREFIX = "pgextbench_stat_"


def _statistics_name(candidate_id: str) -> str:
    return MANAGED_STATISTICS_PREFIX + hashlib.sha256(candidate_id.encode()).hexdigest()[:24]


def _fingerprint_rows(rows: list[tuple[Any, ...]]) -> str:
    data = json.dumps([list(row) for row in rows], sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def verify_ordinary_statistics_fingerprint(
    connection: PostgresConnection,
    relation_identity: str,
    expected_fingerprint: str,
    phase: str,
) -> dict[str, Any]:
    """Verify persisted ordinary ``pg_stats`` state at a lifecycle boundary."""

    if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
        raise ValueError("expected ordinary statistics fingerprint must be a SHA-256 hex digest")
    if not isinstance(phase, str) or not phase.strip():
        raise ValueError("fingerprint verification phase must be nonempty")
    try:
        observed_fingerprint = _fingerprint_rows(connection.ordinary_statistics(relation_identity))
    except Exception as exc:
        raise RuntimeError(
            f"ordinary PostgreSQL statistics fingerprint was unavailable at phase {phase!r}"
        ) from exc
    result = {
        "phase": phase,
        "relation_identity": relation_identity,
        "expected_fingerprint": expected_fingerprint,
        "observed_fingerprint": observed_fingerprint,
        "match": observed_fingerprint == expected_fingerprint,
    }
    if not result["match"]:
        raise RuntimeError(
            f"ordinary PostgreSQL statistics fingerprint drifted at phase {phase!r}: "
            f"expected {expected_fingerprint}, observed {observed_fingerprint}"
        )
    return result


def _database(instance: Any) -> str:
    value = getattr(instance, "database_name", None)
    if not isinstance(value, str) or not value:
        metadata = getattr(instance, "metadata", {})
        value = metadata.get("database_name") if isinstance(metadata, Mapping) else None
    if not isinstance(value, str) or not value:
        raise ValueError("a managed PostgreSQL instance is required")
    return value


class PostgreSQLStatisticsRepositoryProvider:
    """Materialize an explicit catalog under one imported sample realization."""

    def __init__(
        self,
        connection: PostgresConnection | None = None,
        sample_provider: PostgreSQLAnalyzeSampleProvider | None = None,
    ) -> None:
        self.connection = connection or PostgresConnection.from_environment()
        self.sample_provider = sample_provider or PostgreSQLAnalyzeSampleProvider(self.connection)

    def acquire_repository(
        self,
        instance: PostgresInstance,
        sample_artifact: SampleArtifact,
        candidate_catalog: CandidateCatalog,
        *,
        benchmark_id: str,
        artifact_id: str | None = None,
        root: Path | None = None,
        retain_definitions: bool = False,
    ) -> dict[str, Any]:
        if sample_artifact.benchmark_id != benchmark_id:
            raise ValueError("sample artifact benchmark does not match acquisition benchmark")
        if sample_artifact.relation_identity != candidate_catalog.relation_identity:
            raise ValueError("sample relation and candidate catalog relation do not match")
        database_name = validate_managed_database_name(_database(instance))
        artifact_id = artifact_id or f"{benchmark_id}-statistics-repository-v1"
        directory = allocate_repository_artifact_dir(benchmark_id, artifact_id, root)
        payload_dir = directory / "payloads"
        payload_dir.mkdir()
        target = self.connection.for_database(database_name)
        created: list[tuple[str, str]] = []
        imported = False
        analyzed = 0
        states: list[CandidatePayloadState] = []
        cleanup_errors: list[str] = []
        result_payload: dict[str, Any] | None = None
        source = dict(sample_artifact.postgres_source)
        try:
            target.connect()
            relation = candidate_catalog.relation_identity
            schema = relation.split(".", 1)[0]
            self.sample_provider.begin_sample_import(target, sample_artifact, relation, root)
            imported = True
            target.set_default_statistics_target(candidate_catalog.statistics_target)
            names: dict[str, str] = {}
            objects: dict[str, tuple[Any, ...]] = {}
            for candidate in candidate_catalog.candidates:
                name = _statistics_name(candidate.candidate_id)
                if name in names.values():
                    raise RuntimeError(f"managed statistics name collision: {name}")
                if target.statistics_object(schema, name) is not None:
                    raise RuntimeError(f"managed statistics name collision: {schema}.{name}")
                target.create_statistics(schema, name, candidate.kind, candidate.columns, relation)
                created.append((schema, name))
                target.set_statistics_target(schema, name, candidate.statistics_target or candidate_catalog.statistics_target)
                obj = target.statistics_object(schema, name)
                if obj is None:
                    raise RuntimeError(f"statistics object was not created: {candidate.candidate_id}")
                names[candidate.candidate_id] = name
                objects[candidate.candidate_id] = obj

            target.analyze(relation)
            analyzed += 1
            ordinary_fingerprint = _fingerprint_rows(target.ordinary_statistics(relation))
            for candidate in candidate_catalog.candidates:
                row = target.native_statistics_payload(schema, names[candidate.candidate_id], candidate.kind)
                if row is None:
                    raise RuntimeError(f"native statistics object disappeared: {candidate.candidate_id}")
                payload = row[0]
                object_row = objects[candidate.candidate_id]
                metadata = {
                    "statistics_name": names[candidate.candidate_id],
                    "backend_oid_diagnostic": int(object_row[0]),
                    "relation_oid_diagnostic": int(object_row[1]),
                    "stxkind": str(object_row[2]),
                }
                if payload is None:
                    states.append(CandidatePayloadState(
                        candidate_id=candidate.candidate_id, kind=candidate.kind,
                        columns=candidate.columns, state="ABSENT_NATIVE", payload_fingerprint=None,
                        native_metadata=metadata,
                    ))
                    continue
                payload_bytes = bytes(payload)
                if not payload_bytes:
                    raise RuntimeError(f"empty native payload: {candidate.candidate_id}")
                payload_digest = hashlib.sha256(payload_bytes).hexdigest()
                (payload_dir / f"{candidate.candidate_id}.{candidate.kind}.bin").write_bytes(payload_bytes)
                metadata["payload_size"] = len(payload_bytes)
                states.append(CandidatePayloadState(
                    candidate_id=candidate.candidate_id, kind=candidate.kind,
                    columns=candidate.columns, state="PRESENT", payload_fingerprint=payload_digest,
                    native_metadata=metadata,
                ))
            artifact = StatisticsRepositoryArtifact.create(
                artifact_id=artifact_id, benchmark_id=benchmark_id, relation_identity=relation,
                sample_artifact_id=sample_artifact.artifact_id,
                sample_payload_sha256=sample_artifact.payload_sha256,
                candidate_catalog={
                    "catalog_id": candidate_catalog.catalog_id,
                    "catalog_sha256": candidate_catalog.catalog_sha256,
                    "candidate_count": candidate_catalog.candidate_count,
                },
                postgres_source=source,
                statistics_target={
                    "requested": candidate_catalog.statistics_target,
                    "effective": candidate_catalog.statistics_target,
                    "scope": "global",
                },
                ordinary_statistics_fingerprint=ordinary_fingerprint,
                candidate_states=tuple(states),
                repository_digest="0" * 64,
                lineage={
                    "parent_data_artifact_id": sample_artifact.parent_data_artifact_id,
                    "loaded_instance_id": sample_artifact.loaded_instance_id,
                    "sample_artifact_id": sample_artifact.artifact_id,
                    "candidate_catalog_id": candidate_catalog.catalog_id,
                },
            )
            manifest_path = write_repository_artifact(artifact, root)
            result_payload = {
                "status": "PASS", "message": "statistics repository acquisition completed",
                "artifact": artifact, "manifest_path": manifest_path,
                "sample_import_count": 1, "analyze_count": analyzed,
                "present_count": sum(item.state == "PRESENT" for item in states),
                "absent_native_count": sum(item.state == "ABSENT_NATIVE" for item in states),
                "created_statistics_names": tuple(name for _, name in created),
                "cleanup": {"status": "PASS", "objects": tuple(name for _, name in created)},
            }
        except Exception as exc:
            result_payload = {
                "status": "FAIL",
                "message": f"statistics repository acquisition failed: {exc}",
                "error": str(exc),
                "sample_import_count": 1 if imported else 0,
                "analyze_count": analyzed,
                "created_statistics_names": tuple(name for _, name in created),
            }
        finally:
            try:
                should_drop = not retain_definitions or result_payload is None or result_payload.get("status") != "PASS"
                if should_drop:
                    for schema_name, statistics_name in reversed(created):
                        try:
                            target.drop_statistics(schema_name, statistics_name)
                        except Exception as exc:
                            cleanup_errors.append(str(exc))
                if imported:
                    try:
                        self.sample_provider.end_sample_import(target)
                    except Exception as exc:
                        cleanup_errors.append(str(exc))
            finally:
                target.close()
            if result_payload is not None:
                result_payload["cleanup"] = {
                    "status": "PASS" if not cleanup_errors else "FAIL",
                    "objects": tuple(name for _, name in created),
                    "errors": tuple(cleanup_errors),
                    "definitions_retained": bool(retain_definitions and not cleanup_errors),
                }
                if cleanup_errors:
                    result_payload["status"] = "FAIL"
                    result_payload["message"] = "statistics repository acquisition cleanup failed"
        return result_payload


__all__ = [
    "PostgreSQLStatisticsRepositoryProvider",
    "verify_ordinary_statistics_fingerprint",
]
