"""Validation for fixed-sample native statistics repositories."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .candidate_catalog import CandidateCatalog
from .sample_artifacts import SampleArtifact
from .statistics_repository import StatisticsRepositoryArtifact
from .statistics_storage import repository_artifact_dir
from .validation import ValidationCheck, ValidationReport


class StatisticsRepositoryValidator:
    def validate(
        self,
        artifact: StatisticsRepositoryArtifact,
        *,
        sample_artifact: SampleArtifact | None = None,
        candidate_catalog: CandidateCatalog | None = None,
        root: Path | None = None,
    ) -> ValidationReport:
        if not isinstance(artifact, StatisticsRepositoryArtifact):
            raise TypeError("artifact must be a StatisticsRepositoryArtifact")
        digest = artifact.compute_repository_digest()
        digest_ok = artifact.repository_digest == digest
        checks: list[ValidationCheck] = [
            ValidationCheck("manifest_schema", "PASS", "statistics-repository-v1", "statistics-repository-v1"),
            ValidationCheck("repository_digest", "PASS" if digest_ok else "FAIL", artifact.repository_digest, digest),
        ]
        failed = not digest_ok
        if sample_artifact is not None:
            ok = artifact.sample_artifact_id == sample_artifact.artifact_id and artifact.sample_payload_sha256 == sample_artifact.payload_sha256
            checks.append(ValidationCheck("sample_reference", "PASS" if ok else "FAIL", sample_artifact.artifact_id, artifact.sample_artifact_id))
            failed |= not ok
            if not ok:
                return ValidationReport(
                    benchmark_id=artifact.benchmark_id,
                    instance_id=artifact.sample_artifact_id,
                    status="FAIL", checks=tuple(checks), metadata={"candidate_count": len(artifact.candidate_states)},
                )
        if candidate_catalog is not None:
            catalog = artifact.candidate_catalog
            ok = (
                catalog.get("catalog_id") == candidate_catalog.catalog_id
                and catalog.get("catalog_sha256") == candidate_catalog.catalog_sha256
                and catalog.get("candidate_count") == candidate_catalog.candidate_count
                and {item.candidate_id for item in artifact.candidate_states} == {item.candidate_id for item in candidate_catalog.candidates}
            )
            checks.append(ValidationCheck("candidate_catalog", "PASS" if ok else "FAIL", candidate_catalog.catalog_sha256, catalog.get("catalog_sha256")))
            failed |= not ok
            if not ok:
                return ValidationReport(
                    benchmark_id=artifact.benchmark_id,
                    instance_id=artifact.sample_artifact_id,
                    status="FAIL", checks=tuple(checks), metadata={"candidate_count": len(artifact.candidate_states)},
                )
        directory = repository_artifact_dir(artifact.benchmark_id, artifact.artifact_id, root)
        for state in artifact.candidate_states:
            payload = directory / "payloads" / f"{state.candidate_id}.{state.kind}.bin"
            if state.state == "PRESENT":
                ok = (
                    payload.is_file() and not payload.is_symlink()
                    and hashlib.sha256(payload.read_bytes()).hexdigest() == state.payload_fingerprint
                )
                checks.append(ValidationCheck(f"payload_{state.candidate_id}", "PASS" if ok else "FAIL", state.payload_fingerprint, state.payload_fingerprint if ok else None))
                failed |= not ok
            else:
                ok = not payload.exists()
                checks.append(ValidationCheck(f"absent_{state.candidate_id}", "PASS" if ok else "FAIL", False, payload.exists()))
                failed |= not ok
        return ValidationReport(
            benchmark_id=artifact.benchmark_id,
            instance_id=artifact.sample_artifact_id,
            status="FAIL" if failed else "PASS",
            checks=tuple(checks),
            metadata={
                "candidate_count": len(artifact.candidate_states),
                "present_count": sum(item.state == "PRESENT" for item in artifact.candidate_states),
                "absent_native_count": sum(item.state == "ABSENT_NATIVE" for item in artifact.candidate_states),
            },
        )


__all__ = ["StatisticsRepositoryValidator"]
