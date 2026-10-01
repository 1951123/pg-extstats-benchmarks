import pytest
from pgextstats_benchmarks.adapter import BenchmarkAdapter


def test_adapter_is_abstract():
    with pytest.raises(TypeError):
        BenchmarkAdapter()


def test_concrete_adapter_implements_all_stages():
    class ExampleAdapter(BenchmarkAdapter):
        def fetch(self):
            return "raw"

        def prepare(self):
            return "prepared"

        def load(self):
            return "loaded"

        def validate(self):
            return "valid"

        def normalize_workload(self):
            return "workload"

        def collect_truth(self):
            return "truth"

    adapter = ExampleAdapter()
    assert [adapter.fetch(), adapter.prepare(), adapter.load(), adapter.validate(),
            adapter.normalize_workload(), adapter.collect_truth()] == [
                "raw", "prepared", "loaded", "valid", "workload", "truth"]
