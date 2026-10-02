"""Validation of Census source, prepared, and workload artifacts only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from dataclasses import replace

from .artifacts import Artifact
from .instances import LoadedInstance
from .validation import ValidationCheck, ValidationReport
from .validator_registry import register_validator
from .validators import BenchmarkValidator
from .paths import confined_path
from .registry import load_manifest, load_registry, read_mapping
from .truth import TruthArtifact
from .workload_executor import Workload


class CensusValidator(BenchmarkValidator):
    """Check artifact integrity without opening PostgreSQL or executing SQL."""

    def __init__(
        self,
        *,
        data_root: Path | None = None,
        repo_root: Path | None = None,
        source_declarations: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve() if data_root is not None else None
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        self._provided_sources = source_declarations

    def _source_declarations(self) -> dict[str, dict[str, Any]]:
        if self._provided_sources is not None:
            return {key: dict(value) for key, value in self._provided_sources.items()}
        definition = load_registry(self.repo_root)["census"]
        manifest = load_manifest(definition)
        return {
            name: read_mapping(confined_path(definition.path, entry["manifest"]))
            for name, entry in manifest["sources"].items()
        }

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _artifact(value: Artifact | Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
        if isinstance(value, Artifact):
            if value.path is None:
                raise ValueError(f"Artifact has no path: {value.id}")
            directory = Path(value.path)
            manifest = dict(value.metadata)
            if not manifest:
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            return directory, manifest
        directory = Path(value["path"])
        manifest = dict(value.get("metadata", {}))
        if not manifest:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        return directory, manifest

    def validate_artifacts(
        self,
        *,
        raw_artifact: Artifact | Mapping[str, Any],
        prepared_artifact: Artifact | Mapping[str, Any],
        workload_artifact: Artifact | Mapping[str, Any],
        instance_id: str = "census-artifacts-v1",
    ) -> ValidationReport:
        checks: list[ValidationCheck] = []
        raw_dir, raw_manifest = self._artifact(raw_artifact)
        source_zip = raw_dir / "source.zip"
        configured_raw = self._source_declarations().get("data", {})
        raw_expected = configured_raw.get("sha256")
        raw_actual = self._digest(source_zip) if source_zip.is_file() else None
        recorded_raw = raw_manifest.get("sha256")
        raw_ok = raw_actual == raw_expected == recorded_raw
        checks.append(
            ValidationCheck(
                name="raw_artifact_checksum",
                status="PASS" if raw_ok else "FAIL",
                expected=raw_expected,
                actual=raw_actual,
                message="raw archive checksum matches declaration" if raw_ok else "raw archive is missing or differs",
            )
        )

        prepared_dir, prepared_manifest = self._artifact(prepared_artifact)
        members = prepared_manifest.get("archive_members", [])
        missing = []
        for member in members:
            member_path = prepared_dir / member["name"]
            if not member_path.exists():
                missing.append(member["name"])
        checks.append(
            ValidationCheck(
                name="prepared_artifact_extraction",
                status="PASS" if prepared_dir.is_dir() and not missing else "FAIL",
                expected="all archive members present",
                actual="all archive members present" if not missing else missing,
                message="prepared extraction is complete" if not missing else "prepared files are missing",
            )
        )

        workload_dir, workload_manifest = self._artifact(workload_artifact)
        query = workload_dir / "query.sql"
        configured_workload = self._source_declarations().get("workload", {})
        workload_expected = configured_workload.get("sha256")
        workload_actual = self._digest(query) if query.is_file() else None
        recorded_workload = workload_manifest.get("sha256")
        workload_ok = workload_actual == workload_expected == recorded_workload
        checks.append(
            ValidationCheck(
                name="workload_artifact_checksum",
                status="PASS" if workload_ok else "FAIL",
                expected=workload_expected,
                actual=workload_actual,
                message="workload file exists and checksum matches declaration" if workload_ok else "workload file is missing or differs",
            )
        )
        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        return ValidationReport(
            benchmark_id="census",
            instance_id=instance_id,
            status=status,
            checks=tuple(checks),
            metadata={"validator": self.__class__.__name__, "scope": "source-artifacts"},
        )

    @staticmethod
    def _database_checks(result: Mapping[str, Any]) -> tuple[ValidationCheck, ...]:
        checks = []
        for value in result.get("checks", ()):
            if isinstance(value, Mapping) and isinstance(value.get("name"), str):
                checks.append(ValidationCheck.from_dict(value))
        return tuple(checks)

    def validate_loaded_instance(
        self,
        instance: Any,
        loader: Any,
        *,
        raw_artifact: Artifact | Mapping[str, Any],
        prepared_artifact: Artifact | Mapping[str, Any],
        workload_artifact: Artifact | Mapping[str, Any],
    ) -> ValidationReport:
        """Combine source-artifact checks with the PostgreSQL loader report."""
        database_result = loader.validate_instance(instance)
        if not isinstance(database_result, Mapping):
            raise TypeError("loader validation must return a mapping")
        metadata = dict(getattr(instance, "metadata", {}))
        metadata["raw_artifact"] = raw_artifact.to_dict() if isinstance(raw_artifact, Artifact) else dict(raw_artifact)
        metadata["prepared_artifact"] = prepared_artifact.to_dict() if isinstance(prepared_artifact, Artifact) else dict(prepared_artifact)
        metadata["workload_artifact"] = workload_artifact.to_dict() if isinstance(workload_artifact, Artifact) else dict(workload_artifact)
        metadata["database_validation"] = dict(database_result)
        checked_instance = replace(instance, metadata=metadata)
        return self.validate_instance(checked_instance)

    def validate_instance(self, instance: LoadedInstance) -> ValidationReport:
        if not isinstance(instance, LoadedInstance) and not all(
            hasattr(instance, name) for name in ("instance_id", "metadata")
        ):
            raise TypeError("instance must provide instance_id, benchmark_id, and metadata")
        metadata = instance.metadata
        benchmark_id = getattr(instance, "benchmark_id", metadata.get("benchmark_id", "census"))
        try:
            raw = metadata["raw_artifact"]
            prepared = metadata["prepared_artifact"]
            workload = metadata["workload_artifact"]
        except KeyError as exc:
            return ValidationReport(
                benchmark_id=benchmark_id,
                instance_id=instance.instance_id,
                status="FAIL",
                checks=(ValidationCheck("artifact_metadata", "FAIL", message=f"missing {exc.args[0]}"),),
                metadata={"validator": self.__class__.__name__},
            )
        report = self.validate_artifacts(
            raw_artifact=raw,
            prepared_artifact=prepared,
            workload_artifact=workload,
            instance_id=instance.instance_id,
        )
        database_result = metadata.get("database_validation")
        if not isinstance(database_result, Mapping):
            return report
        database_checks = self._database_checks(database_result)
        checks = tuple(report.checks) + database_checks
        status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
        report_metadata = dict(report.metadata)
        report_metadata["database_validation"] = dict(database_result)
        return ValidationReport(
            benchmark_id=report.benchmark_id,
            instance_id=report.instance_id,
            status=status,
            checks=checks,
            metadata=report_metadata,
        )


register_validator("census-validator", CensusValidator)


class CensusTruthValidator(BenchmarkValidator):
    """Validate workload coverage and exact cardinality presence."""

    def validate_truth(self, workload: Workload, truth: TruthArtifact) -> ValidationReport:
        if not isinstance(workload, Workload):
            raise TypeError("workload must be a Workload")
        if not isinstance(truth, TruthArtifact):
            raise TypeError("truth must be a TruthArtifact")
        expected_ids = [query.query_id for query in workload.queries]
        actual_ids = [result.query_id for result in truth.query_results]
        count_ok = workload.query_count == truth.query_count
        ids_ok = len(actual_ids) == len(expected_ids) and set(actual_ids) == set(expected_ids)
        cardinality_ok = all(
            result.status == "PASS" and result.cardinality is not None and result.cardinality >= 0
            for result in truth.query_results
        )
        checks = (
            ValidationCheck(
                "query_count",
                "PASS" if count_ok else "FAIL",
                workload.query_count,
                truth.query_count,
                "workload and truth query counts match" if count_ok else "query count differs",
            ),
            ValidationCheck(
                "query_ids",
                "PASS" if ids_ok else "FAIL",
                expected_ids,
                actual_ids,
                "all query IDs are present" if ids_ok else "query IDs are missing or duplicated",
            ),
            ValidationCheck(
                "cardinality_values",
                "PASS" if cardinality_ok else "FAIL",
                "nonnegative cardinality for every query",
                "present" if cardinality_ok else "missing or failed cardinality",
                "all exact cardinality values are present" if cardinality_ok else "one or more queries failed",
            ),
        )
        return ValidationReport(
            benchmark_id=truth.benchmark_id,
            instance_id=truth.workload_id,
            status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
            checks=checks,
            metadata={"validator": self.__class__.__name__},
        )

    def validate(self, workload: Workload, truth: TruthArtifact) -> ValidationReport:
        return self.validate_truth(workload, truth)

    def validate_instance(self, instance: LoadedInstance) -> ValidationReport:
        if not isinstance(instance, LoadedInstance):
            raise TypeError("instance must be a LoadedInstance")
        try:
            workload = instance.metadata["workload"]
            truth = instance.metadata["truth"]
        except KeyError as exc:
            return ValidationReport(
                benchmark_id=instance.benchmark_id,
                instance_id=instance.instance_id,
                status="FAIL",
                checks=(ValidationCheck("truth_metadata", "FAIL", message=f"missing {exc.args[0]}"),),
            )
        return self.validate_truth(workload, truth)


register_validator("census-truth-validator", CensusTruthValidator)
