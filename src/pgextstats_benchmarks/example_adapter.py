"""Toy adapter used to exercise the lifecycle without external systems."""
from .adapter import BenchmarkAdapter
from .adapters import register_adapter


class ExampleAdapter(BenchmarkAdapter):
    """An entirely in-memory adapter with one successful result per stage."""

    def _completed(self, stage: str) -> dict[str, str]:
        return {"status": "PASS", "message": f"example {stage} completed"}

    def fetch(self) -> dict[str, str]:
        return self._completed("fetch")

    def prepare(self) -> dict[str, str]:
        return self._completed("prepare")

    def load(self) -> dict[str, str]:
        return self._completed("load")

    def validate(self) -> dict[str, str]:
        return self._completed("validate")

    def normalize_workload(self) -> dict[str, str]:
        return self._completed("normalize_workload")

    def collect_truth(self) -> dict[str, str]:
        return self._completed("collect_truth")


register_adapter("example", ExampleAdapter)
