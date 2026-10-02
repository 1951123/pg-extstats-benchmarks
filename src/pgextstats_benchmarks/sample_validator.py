"""Validation of SampleArtifact metadata and its external payload."""
from __future__ import annotations

from pathlib import Path

from .sample_artifacts import SampleArtifact
from .sample_storage import verify_sample_artifact
from .validation import ValidationCheck, ValidationReport


class SampleArtifactValidator:
    """Check the Python-visible contract; PostgreSQL checks binary semantics."""

    def validate(self, artifact: SampleArtifact, root: Path | None = None) -> ValidationReport:
        if not isinstance(artifact, SampleArtifact):
            raise TypeError("artifact must be a SampleArtifact")
        checks: list[ValidationCheck] = [
            ValidationCheck("manifest_schema", "PASS", "PGEXTSC1/v1", f"{artifact.format}/v{artifact.format_version}"),
            ValidationCheck("lineage", "PASS", artifact.parent_data_artifact_id, artifact.lineage.get("parent_artifact_ids")),
        ]
        try:
            payload = verify_sample_artifact(artifact, root)
            checks.append(ValidationCheck("payload_exists", "PASS", True, True))
            checks.append(ValidationCheck("payload_sha256", "PASS", artifact.payload_sha256, artifact.payload_sha256))
            metadata = {"payload_path": str(payload), "sample_tuple_count": artifact.sample_tuple_count}
            status = "PASS"
        except (OSError, ValueError) as exc:
            checks.append(ValidationCheck("payload", "FAIL", True, False, str(exc)))
            metadata = {}
            status = "FAIL"
        return ValidationReport(
            benchmark_id=artifact.benchmark_id,
            instance_id=artifact.loaded_instance_id,
            status=status,
            checks=tuple(checks),
            metadata=metadata,
        )


__all__ = ["SampleArtifactValidator"]
