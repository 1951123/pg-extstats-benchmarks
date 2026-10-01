"""Toy adapter used to exercise the lifecycle without external systems."""
from .adapter import BenchmarkAdapter
from .adapters import register_adapter
from .artifacts import Artifact


class ExampleAdapter(BenchmarkAdapter):
    """An entirely in-memory adapter with one successful result per stage."""

    def _artifact(
        self, artifact_id: str, artifact_type: str, parents: tuple[str, ...] = ()
    ) -> Artifact:
        return Artifact(
            id=artifact_id,
            type=artifact_type,
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
        return self._completed(
            "prepare",
            inputs=(self._artifact("example-raw-v1", "raw_dataset"),),
            outputs=(
                self._artifact(
                    "example-prepared-v1", "prepared_dataset", ("example-raw-v1",)
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
