"""Managed PostgreSQL database lifecycle implementation."""

import csv
from dataclasses import dataclass, replace
from pathlib import Path
import re
import uuid
from typing import Any

from ..loader_registry import register_loader
from ..loaders import DatabaseLoader
from ..artifacts import Artifact
from ..instances import LoadedInstance
from ..validation import ValidationCheck, ValidationReport
from .connection import PostgresConnection
from .instance import PostgresInstance


MANAGED_DATABASE_PREFIX = "pgextbench_"
_NAME_COMPONENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_managed_database_name(database_name: str) -> str:
    """Validate the only database names this loader may destroy."""

    if not isinstance(database_name, str) or not database_name.startswith(MANAGED_DATABASE_PREFIX):
        raise ValueError("database name must start with pgextbench_")
    if database_name in {"postgres", "template0", "template1"}:
        raise ValueError(f"refusing reserved database name: {database_name}")
    if len(database_name) > 63 or not _NAME_COMPONENT.fullmatch(database_name):
        raise ValueError(f"unsafe database identifier: {database_name!r}")
    if not database_name[len(MANAGED_DATABASE_PREFIX):]:
        raise ValueError("managed database name must include a name component")
    return database_name


def is_managed_database_name(database_name: str) -> bool:
    try:
        validate_managed_database_name(database_name)
    except ValueError:
        return False
    return True


def _artifact_file(root: Path, relative_name: object, label: str) -> Path:
    if not isinstance(relative_name, str) or not relative_name.strip():
        raise ValueError(f"artifact {label} path must be a nonempty relative path")
    candidate = (root / relative_name).resolve()
    if Path(relative_name).is_absolute() or not candidate.is_relative_to(root):
        raise ValueError(f"artifact {label} path escapes its artifact directory")
    if not candidate.is_file():
        raise ValueError(f"artifact {label} is missing: {candidate}")
    return candidate


@dataclass
class PostgreSQLLoader(DatabaseLoader):
    """Create, validate, and destroy only ``pgextbench_*`` databases."""

    connection: PostgresConnection | None = None

    def __post_init__(self) -> None:
        if self.connection is None:
            self.connection = PostgresConnection.from_environment()

    @staticmethod
    def database_name_for(name: str) -> str:
        if not isinstance(name, str) or not _NAME_COMPONENT.fullmatch(name):
            raise ValueError(f"unsafe benchmark name: {name!r}")
        database_name = f"{MANAGED_DATABASE_PREFIX}{name}_{uuid.uuid4().hex[:8]}"
        return validate_managed_database_name(database_name)

    def create_instance(self, benchmark_id: str = "test") -> PostgresInstance:
        assert self.connection is not None
        database_name = self.database_name_for(benchmark_id)
        self.connection.create_database(database_name)
        version = self.connection.server_version()
        return PostgresInstance(
            instance_id=database_name,
            database_name=database_name,
            status="READY",
            metadata={
                "benchmark_id": benchmark_id,
                "postgres_version": version,
                "host": self.connection.host,
                "port": self.connection.port,
            },
        )

    def load_artifact(
        self,
        instance: PostgresInstance | LoadedInstance | Artifact,
        artifact: Artifact | None = None,
    ) -> PostgresInstance:
        """Materialize one prepared artifact in a managed database.

        The artifact supplies relative schema/data paths and table metadata;
        no benchmark ID or benchmark-specific table name is embedded here.
        """

        if artifact is None:
            raise TypeError("load_artifact requires a PostgresInstance and an Artifact")
        if not isinstance(instance, PostgresInstance):
            raise TypeError("instance must be a PostgresInstance")
        if not isinstance(artifact, Artifact):
            raise TypeError("artifact must be an Artifact")
        if artifact.type != "prepared_dataset":
            raise ValueError("PostgreSQLLoader requires a prepared_dataset artifact")
        if artifact.path is None:
            raise ValueError("prepared artifact must declare a directory path")
        root = Path(artifact.path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"prepared artifact directory is missing: {root}")
        schema_path = _artifact_file(root, artifact.metadata.get("schema_path", "schema.sql"), "schema")
        data_path = _artifact_file(root, artifact.metadata.get("data_path", "data.csv"), "data")
        table = artifact.metadata.get("table")
        columns = artifact.metadata.get("columns")
        if not isinstance(table, str) or not table:
            raise ValueError("prepared artifact must declare one table")
        if not isinstance(columns, (list, tuple)) or not columns:
            raise ValueError("prepared artifact must declare table columns")
        columns = tuple(columns)
        if not all(isinstance(column, str) and column for column in columns):
            raise ValueError("prepared artifact columns must be nonempty strings")

        with data_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(columns):
                raise ValueError(
                    f"data columns {reader.fieldnames!r} do not match declared columns {list(columns)!r}"
                )
            rows = []
            for row in reader:
                if None in row:
                    raise ValueError("data row has more fields than declared columns")
                rows.append(tuple(row[column] for column in columns))
        expected_rows = artifact.metadata.get("expected_rows", len(rows))
        if not isinstance(expected_rows, int) or expected_rows < 0:
            raise ValueError("expected_rows must be a nonnegative integer")
        if expected_rows != len(rows):
            raise ValueError("prepared artifact row count does not match expected_rows")

        assert self.connection is not None
        target = self.connection.for_database(instance.database_name)
        try:
            target.connect()
            target.execute_script(schema_path.read_text(encoding="utf-8"))
            rows_loaded = target.insert_rows(table, columns, rows)
        finally:
            target.close()

        metadata = dict(instance.metadata)
        artifact_ids = list(metadata.get("artifact_ids", ()))
        if artifact.id not in artifact_ids:
            artifact_ids.append(artifact.id)
        expected_tables = dict(metadata.get("expected_tables", {}))
        expected_tables[table] = expected_rows
        metadata.update(
            {
                "artifact_ids": artifact_ids,
                "artifact_id": artifact.id,
                "expected_tables": expected_tables,
                "tables": sorted(expected_tables),
                "rows_loaded": int(metadata.get("rows_loaded", 0)) + rows_loaded,
                "loader_type": self.__class__.__name__,
            }
        )
        return replace(instance, status="LOADED", metadata=metadata)

    def validate_instance(self, instance: PostgresInstance) -> dict[str, Any]:
        if not isinstance(instance, PostgresInstance):
            raise TypeError("instance must be a PostgresInstance")
        validate_managed_database_name(instance.database_name)
        assert self.connection is not None
        checks: list[ValidationCheck] = []
        metadata = dict(instance.metadata)
        exists = False
        try:
            self.connection.connect()
            checks.append(ValidationCheck("connection_works", "PASS", True, True))
            exists = self.connection.database_exists(instance.database_name)
            checks.append(ValidationCheck("database_exists", "PASS" if exists else "FAIL", True, exists))
        except Exception as exc:
            message = str(exc)
            checks.append(ValidationCheck("connection_works", "FAIL", True, False, message))
            checks.append(ValidationCheck("database_exists", "FAIL", True, False, message))

        version = None
        expected_tables = metadata.get("expected_tables", {})
        if expected_tables and not isinstance(expected_tables, dict):
            raise TypeError("instance expected_tables metadata must be a mapping")
        if exists:
            target = self.connection.for_database(instance.database_name)
            try:
                target.connect()
                version = target.server_version()
                version_status = "PASS" if version.startswith("PostgreSQL 16.14") else "FAIL"
                checks.append(ValidationCheck("version_query", version_status, "PostgreSQL 16.14", version))
                if expected_tables:
                    actual_tables = [
                        table for table in sorted(expected_tables) if target.table_exists(table)
                    ]
                    checks.append(
                        ValidationCheck(
                            "table_exists",
                            "PASS" if actual_tables == sorted(expected_tables) else "FAIL",
                            sorted(expected_tables),
                            actual_tables,
                        )
                    )
                    actual_counts = {
                        table: target.row_count(table)
                        for table in actual_tables
                    }
                    row_status = "PASS" if actual_counts == expected_tables else "FAIL"
                    checks.append(
                        ValidationCheck("row_count", row_status, expected_tables, actual_counts)
                    )
            except Exception as exc:
                checks.append(ValidationCheck("version_query", "FAIL", "PostgreSQL 16.14", None, str(exc)))
                if expected_tables:
                    checks.append(ValidationCheck("table_exists", "FAIL", sorted(expected_tables), None, str(exc)))
                    checks.append(ValidationCheck("row_count", "FAIL", expected_tables, None, str(exc)))
            finally:
                target.close()
        else:
            checks.append(ValidationCheck("version_query", "FAIL", "PostgreSQL 16.14", None, "database does not exist"))
            if expected_tables:
                checks.append(ValidationCheck("table_exists", "FAIL", sorted(expected_tables), [], "database does not exist"))
                checks.append(ValidationCheck("row_count", "FAIL", expected_tables, {}, "database does not exist"))
        if version is not None:
            metadata["postgres_version"] = version
        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        report = ValidationReport(
            benchmark_id=str(metadata.get("benchmark_id", "postgres")),
            instance_id=instance.instance_id,
            status=status,
            checks=tuple(checks),
            metadata=metadata,
        )
        result = report.to_dict()
        result["message"] = f"{self.__class__.__name__} validation {status.lower()}"
        return result

    def destroy_instance(self, instance: PostgresInstance) -> dict[str, Any]:
        if not isinstance(instance, PostgresInstance):
            raise TypeError("instance must be a PostgresInstance")
        validate_managed_database_name(instance.database_name)
        assert self.connection is not None
        self.connection.drop_database(instance.database_name)
        return {
            "status": "PASS",
            "message": f"destroyed managed database {instance.database_name}",
            "instance_id": instance.instance_id,
        }

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()


register_loader("postgres", PostgreSQLLoader)
