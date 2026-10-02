"""PostgreSQL provider for opaque PGEXTSC1 ANALYZE sample artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from ..sample_artifacts import SampleArtifact
from ..sample_storage import (
    allocate_sample_artifact_dir,
    verify_sample_artifact,
    write_sample_manifest,
)
from ..paths import benchmark_data_root
from .connection import PostgresConnection
from .instance import PostgresInstance


EXPORT_GUC = "pgextadv.analyze_sample_export"
IMPORT_GUC = "pgextadv.analyze_sample_import"
FORMAT = "PGEXTSC1"
FORMAT_VERSION = 1
AUTHORITATIVE_SOURCE = "https://github.com/1951123/postgresql-pgextadv"
AUTHORITATIVE_COMMIT = "7e992ab6438fef2f8eb98c7a9ed30c9f1c816ce7"
UPSTREAM_BASE = "0d1c00c624fa7367d4a895f44381887757289682"
SERVER_VERSION = "16.14"
AUTHORITATIVE_BINARY_SHA256 = "42269178123301ccedf4db5d54bd7d8885ae3b17ef6ba987456cc231e0d930e4"
NOTICE_RE = re.compile(r"(?P<tuples>\d+) rows in sample, (?P<total>\d+(?:\.\d+)?) estimated total rows")


@dataclass(frozen=True)
class SampleReplayResult:
    status: str
    message: str
    artifact_id: str
    relation_identity: str
    payload_sha256: str
    postgres_source: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "artifact_id": self.artifact_id,
            "relation_identity": self.relation_identity,
            "payload_sha256": self.payload_sha256,
            "postgres_source": dict(self.postgres_source),
        }


def _instance_database(instance: Any) -> str:
    database = getattr(instance, "database_name", None)
    if not isinstance(database, str) or not database:
        metadata = getattr(instance, "metadata", {})
        database = metadata.get("database_name") if isinstance(metadata, Mapping) else None
    if not isinstance(database, str) or not database:
        raise ValueError("a managed PostgreSQL instance is required")
    return database


def _schema_fingerprint(rows: list[tuple[Any, ...]]) -> str:
    canonical = [list(row[1:]) for row in rows]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


class PostgreSQLAnalyzeSampleProvider:
    """Capture and replay one server-native ANALYZE sample realization."""

    def __init__(
        self,
        connection: PostgresConnection | None = None,
        *,
        binary_sha256: str | None = None,
        source_commit: str = AUTHORITATIVE_COMMIT,
    ) -> None:
        self.connection = connection or PostgresConnection.from_environment()
        self.binary_sha256 = (
            binary_sha256
            or os.environ.get("PGEXTADV_POSTGRES_BINARY_SHA256")
            or AUTHORITATIVE_BINARY_SHA256
        )
        self.source_commit = source_commit

    def capability_probe(self, connection: PostgresConnection | None = None) -> dict[str, str]:
        """Read the two extension GUCs; vanilla PostgreSQL fails closed."""

        target = connection or self.connection
        try:
            rows = target.execute(
                "SELECT current_setting(%s), current_setting(%s)",
                (EXPORT_GUC, IMPORT_GUC),
            )
        except Exception as exc:
            raise RuntimeError(
                "connected PostgreSQL server does not expose pgextadv ANALYZE sample-cache capability"
            ) from exc
        if not rows or len(rows[0]) != 2:
            raise RuntimeError("sample-cache capability probe returned no GUC values")
        return {"export_guc": str(rows[0][0]), "import_guc": str(rows[0][1])}

    @staticmethod
    def _reset_modes(connection: PostgresConnection) -> None:
        # The authoritative GUC declarations document an empty value as the
        # supported disabled state; this is not a guessed NULL/reset value.
        connection.set_config(EXPORT_GUC, "")
        connection.set_config(IMPORT_GUC, "")

    @staticmethod
    def _extract_sample_metadata(connection: PostgresConnection) -> tuple[int, float]:
        matches: list[re.Match[str]] = []
        for notice in connection.notices():
            match = NOTICE_RE.search(notice)
            if match:
                matches.append(match)
        if not matches:
            raise RuntimeError("PostgreSQL did not report ANALYZE sample metadata")
        match = matches[-1]
        return int(match.group("tuples")), float(match.group("total"))

    def _source_metadata(self, server_version: str) -> dict[str, Any]:
        return {
            "repository": AUTHORITATIVE_SOURCE,
            "source_commit": self.source_commit,
            "upstream_base_commit": UPSTREAM_BASE,
            "server_version": server_version,
            "binary_sha256": self.binary_sha256,
        }

    def capture_sample(
        self,
        instance: PostgresInstance,
        relation_identity: str,
        *,
        benchmark_id: str,
        parent_data_artifact_id: str,
        artifact_id: str | None = None,
        root: Path | None = None,
    ) -> dict[str, Any]:
        """Export one sample to a newly allocated external artifact directory."""

        artifact_id = artifact_id or f"{benchmark_id}-sample-v1"
        directory = allocate_sample_artifact_dir(benchmark_id, artifact_id, root)
        base = Path(root).expanduser().resolve() if root is not None else benchmark_data_root()
        payload = directory / "sample.bin"
        target = self.connection.for_database(_instance_database(instance))
        connected = False
        capability_ok = False
        previous_client_min_messages = "notice"
        try:
            target.connect()
            connected = True
            self.capability_probe(target)
            capability_ok = True
            server_version = target.server_version()
            if not server_version.startswith(f"PostgreSQL {SERVER_VERSION}"):
                raise RuntimeError(f"unsupported PostgreSQL server version: {server_version}")
            relation_rows = target.relation_metadata(relation_identity)
            if not relation_rows:
                raise ValueError(f"relation does not exist: {relation_identity}")
            setting = target.execute("SELECT current_setting('client_min_messages')")
            if setting and setting[0] and isinstance(setting[0][0], str):
                previous_client_min_messages = setting[0][0]
            self._reset_modes(target)
            # Non-verbose ANALYZE reports the sample count at DEBUG2;
            # debug5 is the lowest accepted threshold and forwards it.
            target.set_config("client_min_messages", "debug5")
            target.set_config(EXPORT_GUC, str(payload))
            clear_notices = getattr(target, "clear_notices", None)
            if callable(clear_notices):
                clear_notices()
            target.analyze(relation_identity)
            tuple_count, total_rows = self._extract_sample_metadata(target)
        finally:
            if connected and capability_ok:
                try:
                    self._reset_modes(target)
                    target.set_config("client_min_messages", previous_client_min_messages)
                finally:
                    target.close()
            else:
                target.close()
        if not payload.is_file() or payload.is_symlink():
            raise FileNotFoundError(f"PostgreSQL did not create sample payload: {payload}")
        digest = hashlib.sha256(payload.read_bytes()).hexdigest()
        relative = payload.relative_to(base).as_posix()
        timestamp = datetime.now(timezone.utc).isoformat()
        artifact = SampleArtifact(
            artifact_id=artifact_id,
            benchmark_id=benchmark_id,
            relation_identity=relation_identity,
            parent_data_artifact_id=parent_data_artifact_id,
            loaded_instance_id=instance.instance_id,
            format=FORMAT,
            format_version=FORMAT_VERSION,
            payload_relative_path=relative,
            payload_sha256=digest,
            sample_tuple_count=tuple_count,
            estimated_total_rows=total_rows,
            postgres_source=self._source_metadata(server_version),
            acquisition={
                "mechanism": "postgres_analyze_sample_cache",
                "source_relation_identity": relation_identity,
                "source_relation_oid_diagnostic": relation_rows[0][0],
                "timestamp": timestamp,
            },
            schema_fingerprint=_schema_fingerprint(relation_rows),
            lineage={
                "parent_artifact_ids": [parent_data_artifact_id],
                "loaded_instance_id": instance.instance_id,
            },
        )
        manifest_path = write_sample_manifest(artifact, root)
        return {
            "status": "PASS",
            "message": "PostgreSQL ANALYZE sample capture completed",
            "artifact": artifact,
            "manifest_path": manifest_path,
            "tuple_count": tuple_count,
            "estimated_total_rows": total_rows,
        }

    def replay_sample(
        self,
        instance: PostgresInstance,
        artifact: SampleArtifact,
        *,
        relation_identity: str | None = None,
        root: Path | None = None,
    ) -> SampleReplayResult:
        """Replay an opaque sample; PostgreSQL validates its deep compatibility."""

        payload = verify_sample_artifact(artifact, root)
        relation = relation_identity or artifact.relation_identity
        if relation != artifact.relation_identity:
            raise ValueError("replay relation does not match sample artifact identity")
        source_commit = artifact.postgres_source.get("source_commit")
        if source_commit != self.source_commit:
            raise RuntimeError("sample artifact PostgreSQL source commit is incompatible")
        target = self.connection.for_database(_instance_database(instance))
        connected = False
        capability_ok = False
        try:
            target.connect()
            connected = True
            self.capability_probe(target)
            capability_ok = True
            server_version = target.server_version()
            if not server_version.startswith(f"PostgreSQL {SERVER_VERSION}"):
                raise RuntimeError(f"unsupported PostgreSQL server version: {server_version}")
            self._reset_modes(target)
            target.set_config(IMPORT_GUC, str(payload))
            target.analyze(relation)
        finally:
            if connected and capability_ok:
                try:
                    self._reset_modes(target)
                finally:
                    target.close()
            else:
                target.close()
        return SampleReplayResult(
            status="PASS",
            message="PostgreSQL ANALYZE sample replay completed",
            artifact_id=artifact.artifact_id,
            relation_identity=relation,
            payload_sha256=artifact.payload_sha256,
            postgres_source=dict(artifact.postgres_source),
        )


__all__ = ["PostgreSQLAnalyzeSampleProvider", "SampleReplayResult"]
