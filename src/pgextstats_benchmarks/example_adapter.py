"""Toy adapter used to exercise the lifecycle without external systems."""
from pathlib import Path

from .adapter import BenchmarkAdapter
from .adapters import register_adapter
from .artifacts import Artifact


class ExampleAdapter(BenchmarkAdapter):
    """An entirely in-memory adapter with one successful result per stage."""

    def _artifact(
        self,
        artifact_id: str,
        artifact_type: str,
        parents: tuple[str, ...] = (),
        *,
        path: Path | None = None,
        metadata: dict | None = None,
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type=artifact_type,
            path=path,
            metadata=metadata or {},
            created_by=self.__class__.__name__,
            creation_info={"source": "in-memory example adapter"},
            parent_artifacts=parents,
        )

    def _completed(
        self,
        stage: str,
        inputs: tuple[Artifact, ...] = (),
        outputs: tuple[Artifact, ...] = (),
    ) -> dict:
        return {
            "status": "PASS",
            "message": f"example {stage} completed",
            "input_artifacts": inputs,
            "output_artifacts": outputs,
        }

    def fetch(self) -> dict:
        return self._completed(
            "fetch", outputs=(self._artifact("example-raw-v1", "raw_dataset"),)
        )

    def prepare(self) -> dict:
        artifact_root = (
            Path(__file__).resolve().parents[2]
            / "benchmarks"
            / "example"
            / "artifacts"
            / "example-prepared-v1"
        )
        return self._completed(
            "prepare",
            inputs=(self._artifact("example-raw-v1", "raw_dataset"),),
            outputs=(
                self._artifact(
                    "example-prepared-v1",
                    "prepared_dataset",
                    ("example-raw-v1",),
                    path=artifact_root,
                    metadata={
                        "schema_path": "schema.sql",
                        "data_path": "data.csv",
                        "table": "example_table",
                        "columns": ["id", "value"],
                        "expected_rows": 2,
                    },
                ),
            ),
        )

    def load(self) -> dict:
        return self._completed(
            "load",
            inputs=(self._artifact("example-prepared-v1", "prepared_dataset"),),
            outputs=(
                self._artifact(
                    "example-loaded-v1", "other", ("example-prepared-v1",)
                ),
            ),
        )

    def validate(self) -> dict:
        return self._completed(
            "validate", inputs=(self._artifact("example-loaded-v1", "other"),)
        )

    def normalize_workload(self) -> dict:
        return self._completed(
            "normalize_workload",
            outputs=(self._artifact("example-workload-v1", "workload"),),
        )

    def collect_truth(self) -> dict:
        return self._completed(
            "collect_truth",
            inputs=(self._artifact("example-loaded-v1", "other"),),
            outputs=(self._artifact("example-truth-v1", "truth"),),
        )


register_adapter("example", ExampleAdapter)
