import pytest

from pgextstats_benchmarks.adapters import get_adapter, list_adapters
from pgextstats_benchmarks.example_adapter import ExampleAdapter
from pgextstats_benchmarks.executor import STAGES, run_stage
from pgextstats_benchmarks.cli import main


def test_builtin_adapter_registration_and_lookup():
    assert "example" in list_adapters()
    assert get_adapter("example") is ExampleAdapter


@pytest.mark.parametrize("stage", STAGES)
def test_executor_runs_every_example_stage(stage):
    result = run_stage("example", stage)
    assert result == {
        "benchmark_id": "example",
        "adapter": "ExampleAdapter",
        "stage": stage,
        "status": "PASS",
        "message": f"example {stage} completed",
    }


def test_executor_rejects_unknown_benchmark_and_stage():
    with pytest.raises(ValueError, match="Unknown benchmark"):
        run_stage("missing", "prepare")
    with pytest.raises(ValueError, match="Invalid stage"):
        run_stage("example", "unknown")


def test_cli_run(capsys):
    assert main(["run", "example", "--stage", "prepare"]) == 0
    output = capsys.readouterr().out
    assert "Benchmark: example" in output
    assert "Adapter: ExampleAdapter" in output
    assert "Stage: prepare" in output
    assert "Status: PASS" in output
    assert "Message: example prepare completed" in output


def test_cli_run_invalid_inputs(capsys):
    assert main(["run", "missing", "--stage", "prepare"]) == 1
    assert "Unknown benchmark" in capsys.readouterr().err
    assert main(["run", "example", "--stage", "unknown"]) == 1
    assert "Invalid stage" in capsys.readouterr().err
