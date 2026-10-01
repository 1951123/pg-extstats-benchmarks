"""Managed PostgreSQL database lifecycle implementation."""

from dataclasses import dataclass
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
        instance: LoadedInstance | Artifact,
        artifact: Artifact | None = None,
    ) -> LoadedInstance:
        """Reject data loading until a later PostgreSQL loader phase."""

        raise NotImplementedError(
            "PostgreSQL artifact loading is not part of the instance lifecycle phase"
        )

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
        if exists:
            target = self.connection.for_database(instance.database_name)
            try:
                target.connect()
                version = target.server_version()
                checks.append(ValidationCheck("version_query", "PASS", "PostgreSQL 16.14", version))
            except Exception as exc:
                checks.append(ValidationCheck("version_query", "FAIL", "PostgreSQL 16.14", None, str(exc)))
            finally:
                target.close()
        else:
            checks.append(ValidationCheck("version_query", "FAIL", "PostgreSQL 16.14", None, "database does not exist"))
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
        return report.to_dict()

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
