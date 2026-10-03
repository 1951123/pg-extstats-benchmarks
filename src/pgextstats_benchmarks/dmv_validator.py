"""Validation contracts for DMV source, database, and truth artifacts."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .artifacts import Artifact
from .dmv_adapter import DMV_COLUMNS
from .instances import LoadedInstance
from .paths import confined_path
from .registry import load_manifest, load_registry, read_mapping
from .truth import TruthArtifact
from .validation import ValidationCheck, ValidationReport
from .validator_registry import register_validator
from .validators import BenchmarkValidator
from .workload_executor import Workload


class DMVValidator(BenchmarkValidator):
    """Validate DMV artifacts and, when supplied, a loaded PostgreSQL instance."""

    def __init__(self, *, data_root: Path | None = None, repo_root: Path | None = None,
                 source_declarations: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.data_root = Path(data_root).expanduser().resolve() if data_root is not None else None
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        self._provided_sources = source_declarations

    def _source_declarations(self) -> dict[str, dict[str, Any]]:
        if self._provided_sources is not None:
            return {key: dict(value) for key, value in self._provided_sources.items()}
        definition = load_registry(self.repo_root)["dmv"]
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
        else:
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
        instance_id: str = "dmv-artifacts-v1",
    ) -> ValidationReport:
        checks: list[ValidationCheck] = []
        raw_dir, raw_manifest = self._artifact(raw_artifact)
        raw_payload = raw_dir / str(raw_manifest.get("payload_path", "data.tar.gz"))
        expected_raw = self._source_declarations().get("data", {}).get("sha256")
        actual_raw = self._digest(raw_payload) if raw_payload.is_file() else None
        recorded_raw = raw_manifest.get("sha256")
        raw_ok = actual_raw == expected_raw == recorded_raw
        checks.append(ValidationCheck(
            "raw_artifact_checksum", "PASS" if raw_ok else "FAIL", expected_raw, actual_raw,
            "raw archive checksum matches declaration" if raw_ok else "raw archive is missing or differs",
        ))

        prepared_dir, prepared_manifest = self._artifact(prepared_artifact)
        members = prepared_manifest.get("archive_members", [])
        missing: list[str] = []
        if not isinstance(members, list):
            missing.append("archive_members metadata")
        else:
            for member in members:
                if not isinstance(member, Mapping) or not isinstance(member.get("name"), str):
                    missing.append("invalid member metadata")
                    continue
                try:
                    member_path = confined_path(prepared_dir, member["name"])
                except ValueError:
                    missing.append(str(member.get("name")))
                    continue
                if not member_path.exists():
                    missing.append(str(member["name"]))
        data_path = prepared_manifest.get("data_path")
        schema_path = prepared_manifest.get("schema_path")
        prepared_ok = (
            prepared_dir.is_dir()
            and not missing
            and isinstance(data_path, str)
            and isinstance(schema_path, str)
            and (prepared_dir / data_path).is_file()
            and (prepared_dir / schema_path).is_file()
            and prepared_manifest.get("table") == "dmv"
            and prepared_manifest.get("columns") == list(DMV_COLUMNS)
            and isinstance(prepared_manifest.get("expected_rows"), int)
            and prepared_manifest.get("expected_rows", -1) >= 0
        )
        checks.append(ValidationCheck(
            "prepared_artifact_extraction", "PASS" if prepared_ok else "FAIL",
            "all archive members, schema, and DMV data present", "complete" if prepared_ok else missing or "invalid metadata",
            "prepared extraction is complete" if prepared_ok else "prepared files or metadata are missing",
        ))

        workload_dir, workload_manifest = self._artifact(workload_artifact)
        source_path = workload_dir / str(workload_manifest.get("source_payload_path", "source_query.sql"))
        normalized_path = workload_dir / str(workload_manifest.get("normalized_payload_path", "query.sql"))
        expected_workload = self._source_declarations().get("workload", {}).get("sha256")
        actual_workload = self._digest(source_path) if source_path.is_file() else None
        normalized_actual = self._digest(normalized_path) if normalized_path.is_file() else None
        workload_ok = (
            actual_workload == expected_workload == workload_manifest.get("source_checksum")
            and normalized_actual == workload_manifest.get("sha256")
            and isinstance(workload_manifest.get("query_count"), int)
            and workload_manifest.get("query_count", 0) > 0
        )
        checks.append(ValidationCheck(
            "workload_artifact_checksum", "PASS" if workload_ok else "FAIL", expected_workload,
            actual_workload, "source and normalized workload checksums match" if workload_ok else "workload source or normalized artifact differs",
        ))
        return ValidationReport(
            benchmark_id="dmv", instance_id=instance_id,
            status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
            checks=tuple(checks), metadata={"validator": self.__class__.__name__, "scope": "source-artifacts"},
        )

    def validate_loaded_instance(
        self, instance: Any, loader: Any, *, raw_artifact: Artifact | Mapping[str, Any],
        prepared_artifact: Artifact | Mapping[str, Any], workload_artifact: Artifact | Mapping[str, Any],
    ) -> ValidationReport:
        database_result = loader.validate_instance(instance)
        if not isinstance(database_result, Mapping):
            raise TypeError("loader validation must return a mapping")
        report = self.validate_artifacts(
            raw_artifact=raw_artifact, prepared_artifact=prepared_artifact,
            workload_artifact=workload_artifact, instance_id=instance.instance_id,
        )
        checks = list(report.checks)
        checks.extend(
            ValidationCheck(
                check["name"], check["status"], check.get("expected"), check.get("actual"), check.get("message", "")
            )
            for check in database_result.get("checks", ())
        )
        metadata = dict(report.metadata)
        metadata.update({"database": dict(database_result), "benchmark_id": "dmv"})
        return replace(
            report,
            instance_id=instance.instance_id,
            status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
            checks=tuple(checks), metadata=metadata,
        )

    def validate_instance(self, instance: LoadedInstance) -> ValidationReport:
        metadata = dict(instance.metadata)
        try:
            raw = metadata["raw_artifact"]
            prepared = metadata["prepared_artifact"]
            workload = metadata["workload_artifact"]
        except KeyError as exc:
            return ValidationReport(
                benchmark_id="dmv", instance_id=instance.instance_id, status="FAIL",
                checks=(ValidationCheck("artifact_metadata", "FAIL", message=f"missing {exc.args[0]}"),),
            )
        return self.validate_artifacts(
            raw_artifact=raw, prepared_artifact=prepared, workload_artifact=workload,
            instance_id=instance.instance_id,
        )


class DMVTruthValidator(BenchmarkValidator):
    """Validate workload coverage and exact cardinality presence for DMV."""

    def validate_truth(self, workload: Workload, truth: TruthArtifact) -> ValidationReport:
        if not isinstance(workload, Workload):
            raise TypeError("workload must be a Workload")
        if not isinstance(truth, TruthArtifact):
            raise TypeError("truth must be a TruthArtifact")
        expected_ids = [query.query_id for query in workload.queries]
        actual_ids = [result.query_id for result in truth.query_results]
        count_ok = workload.query_count == truth.query_count
        ids_ok = expected_ids == actual_ids
        cardinalities_ok = all(
            result.status == "PASS" and isinstance(result.execution_metadata.get("cardinality"), int)
            for result in truth.query_results
        )
        checks = (
            ValidationCheck("query_count", "PASS" if count_ok else "FAIL", workload.query_count, truth.query_count),
            ValidationCheck("query_ids", "PASS" if ids_ok else "FAIL", expected_ids, actual_ids),
            ValidationCheck("cardinality_values", "PASS" if cardinalities_ok else "FAIL", "integer cardinality for every query", "present" if cardinalities_ok else "missing"),
        )
        return ValidationReport(
            benchmark_id="dmv", instance_id=truth.workload_id,
            status="PASS" if all(check.status == "PASS" for check in checks) else "FAIL",
            checks=checks, metadata={"validator": self.__class__.__name__},
        )

    def validate(self, workload: Workload, truth: TruthArtifact) -> ValidationReport:
        return self.validate_truth(workload, truth)

    def validate_instance(self, instance: LoadedInstance) -> ValidationReport:
        try:
            workload = instance.metadata["workload"]
            truth = instance.metadata["truth"]
        except KeyError as exc:
            return ValidationReport(
                benchmark_id="dmv", instance_id=instance.instance_id, status="FAIL",
                checks=(ValidationCheck("truth_metadata", "FAIL", message=f"missing {exc.args[0]}"),),
            )
        return self.validate_truth(workload, truth)


register_validator("dmv-validator", DMVValidator)
register_validator("dmv-truth-validator", DMVTruthValidator)

__all__ = ["DMVValidator", "DMVTruthValidator"]
