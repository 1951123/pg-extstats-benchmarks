"""PostgreSQL backend-local hypothetical configuration provider."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..statistics_configuration import StatisticsConfiguration
from ..statistics_repository import StatisticsRepositoryArtifact
from ..statistics_storage import repository_artifact_dir
from .connection import PostgresConnection
from .instance import PostgresInstance
from .loader import validate_managed_database_name


_KIND_CODE = {"mcv": "m", "fd": "f"}
PLANNER_ORDER_CONTRACT = "advisor-precedence-v1"


class PostgreSQLStatisticsConfigurationProvider:
    """Register one repository once and switch exact candidate subsets."""

    def __init__(self, connection: PostgresConnection | None = None) -> None:
        self.connection = connection or PostgresConnection.from_environment()
        self.target: PostgresConnection | None = None
        self.repository: StatisticsRepositoryArtifact | None = None
        self._oids: dict[str, int] = {}
        self._relation_oid: int | None = None
        self._relation_columns: tuple[str, ...] = ()
        self.registration_calls = 0
        self.activation_calls = 0
        self.reset_calls = 0

    def bind_instance(self, instance: PostgresInstance) -> PostgresConnection:
        validate_managed_database_name(instance.database_name)
        if self.target is None or self.target.database != instance.database_name:
            if self.target is not None:
                self.target.close()
            self.target = self.connection.for_database(instance.database_name)
            self.repository = None
            self._oids.clear()
            self._relation_oid = None
            self._relation_columns = ()
        self.target.connect()
        return self.target

    @staticmethod
    def _payload_path(repository: StatisticsRepositoryArtifact, candidate_id: str, kind: str, root: Path | None) -> Path:
        path = repository_artifact_dir(repository.benchmark_id, repository.artifact_id, root) / "payloads" / f"{candidate_id}.{kind}.bin"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"repository payload is missing: {path}")
        return path

    def register_repository(
        self,
        instance: PostgresInstance,
        repository: StatisticsRepositoryArtifact,
        *,
        root: Path | None = None,
    ) -> dict[str, Any]:
        target = self.bind_instance(instance)
        if self.repository is not None:
            if self.repository.repository_digest != repository.repository_digest:
                raise RuntimeError("a different repository is already registered in this backend session")
            return {"status": "PASS", "registered": False, "registration_calls": self.registration_calls}
        target.hypothetical_reset()
        self.reset_calls += 1
        relation = repository.relation_identity
        schema, _relation_name = relation.split(".", 1)
        relation_oid = target.relation_oid(relation)
        oids: dict[str, int] = {}
        catalogless = callable(getattr(target, "hypothetical_register_definition", None))
        relation_columns = target.table_columns(_relation_name) if catalogless else []
        self._relation_columns = tuple(relation_columns)
        for state in repository.candidate_states:
            metadata = dict(state.native_metadata)
            kind_code = _KIND_CODE[state.kind]
            if catalogless:
                try:
                    attribute_keys = [relation_columns.index(column) + 1 for column in state.columns]
                except ValueError as exc:
                    raise RuntimeError(f"repository column is missing from relation for {state.candidate_id}") from exc
                if state.state == "PRESENT":
                    payload_path = self._payload_path(repository, state.candidate_id, state.kind, root)
                    payload = payload_path.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != state.payload_fingerprint:
                        raise ValueError(f"repository payload checksum mismatch for {state.candidate_id}")
                    backend_oid = target.hypothetical_register_definition(
                        state.candidate_id, relation_oid, kind_code, attribute_keys, payload
                    )
                elif state.state == "ABSENT_NATIVE":
                    backend_oid = target.hypothetical_register_definition_absent(
                        state.candidate_id, relation_oid, kind_code, attribute_keys
                    )
                else:
                    raise ValueError(f"unsupported repository state: {state.state}")
            else:
                statistics_name = metadata.get("statistics_name")
                if not isinstance(statistics_name, str) or not statistics_name.startswith("pgextbench_stat_"):
                    raise ValueError(f"managed statistics name is missing for {state.candidate_id}")
                object_row = target.statistics_object(schema, statistics_name)
                if object_row is None:
                    raise RuntimeError(f"catalog definition is missing for {state.candidate_id}")
                backend_oid, actual_relation_oid, kinds, _name = object_row
                if int(actual_relation_oid) != relation_oid:
                    raise RuntimeError(f"relation mismatch for {state.candidate_id}")
                if kind_code not in str(kinds):
                    raise RuntimeError(f"statistics kind mismatch for {state.candidate_id}")
                backend_oid = int(backend_oid)
                if state.state == "PRESENT":
                    payload_path = self._payload_path(repository, state.candidate_id, state.kind, root)
                    payload = payload_path.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != state.payload_fingerprint:
                        raise ValueError(f"repository payload checksum mismatch for {state.candidate_id}")
                    target.hypothetical_register(backend_oid, relation_oid, kind_code, payload)
                elif state.state == "ABSENT_NATIVE":
                    target.hypothetical_register_absent(backend_oid, relation_oid, kind_code)
                else:
                    raise ValueError(f"unsupported repository state: {state.state}")
            oids[state.candidate_id] = backend_oid
            self.registration_calls += 1
        self.repository = repository
        self._oids = oids
        self._relation_oid = relation_oid
        return {"status": "PASS", "registered": True, "registration_calls": self.registration_calls,
                "catalogless": catalogless}

    def canonical_planner_order(self, candidate_ids: Any) -> tuple[str, ...]:
        """Resolve membership to the frozen advisor precedence contract.

        ``StatisticsConfiguration`` serializes membership lexically for stable
        JSON/digests.  PostgreSQL's greedy extended-statistics selection uses
        the planner-visible list order, so replay must resolve that membership
        through the same precedence key used by the advisor search.
        """
        if self.repository is None:
            raise RuntimeError("repository is not registered")
        selected = set(candidate_ids)
        states = {state.candidate_id: state for state in self.repository.candidate_states}
        unknown = selected - states.keys()
        if unknown:
            raise ValueError(f"configuration references unknown candidates: {sorted(unknown)}")
        positions = {column: index + 1 for index, column in enumerate(self._relation_columns)}
        def key(candidate_id: str) -> tuple[Any, ...]:
            state = states[candidate_id]
            if positions:
                try:
                    column_positions = tuple(positions[column] for column in state.columns)
                except KeyError as exc:
                    raise RuntimeError(f"repository column is missing from relation for {candidate_id}") from exc
            else:
                # Physical-statistics test doubles may not expose relation
                # metadata.  Catalogless replay always has it; this fallback
                # keeps the non-catalogless adapter API backwards-compatible.
                column_positions = tuple(sorted(state.columns))
            return (0 if state.kind == "mcv" else 1, len(state.columns), column_positions, tuple(state.columns), candidate_id)
        return tuple(sorted(selected, key=key))

    def activate(self, configuration: StatisticsConfiguration) -> list[str]:
        if self.repository is None or self.target is None:
            raise RuntimeError("repository is not registered")
        configuration.validate_against(self.repository)
        planner_order = self.canonical_planner_order(configuration.selected_candidate_ids)
        requested = [self._oids[item] for item in planner_order]
        active = self.target.hypothetical_activate(requested)
        self.activation_calls += 1
        if active != requested:
            raise RuntimeError("backend active design does not match requested configuration")
        return list(planner_order)

    def reset_configuration(self) -> None:
        if self.repository is None or self.target is None:
            return
        active = self.target.hypothetical_activate([])
        self.activation_calls += 1
        self.reset_calls += 1
        if active:
            raise RuntimeError("hypothetical configuration reset left active candidates")

    def reset(self) -> None:
        if self.target is not None:
            self.target.hypothetical_reset()
            self.reset_calls += 1
        self.repository = None
        self._oids.clear()
        self._relation_oid = None
        self._relation_columns = ()

    def active_candidate_ids(self) -> tuple[str, ...]:
        if self.repository is None or self.target is None:
            return ()
        active = self.target.hypothetical_active()
        reverse = {oid: candidate_id for candidate_id, oid in self._oids.items()}
        try:
            return tuple(reverse[oid] for oid in active)
        except KeyError as exc:
            raise RuntimeError("backend active state contains an unregistered OID") from exc

    def close(self) -> None:
        if self.target is not None:
            self.target.close()
        self.connection.close()


__all__ = ["PLANNER_ORDER_CONTRACT", "PostgreSQLStatisticsConfigurationProvider"]
