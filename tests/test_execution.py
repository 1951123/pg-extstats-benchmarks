import json
from pathlib import Path

from pgextstats_benchmarks.cli import main
from pgextstats_benchmarks.execution import ExecutionRecord
from pgextstats_benchmarks.executor import run_stage


def test_execution_record_serialization():
    record = ExecutionRecord(
        execution_id="abc123",
        benchmark_id="example",
        stage="prepare",
        status="PASS",
        repository_commit="deadbeef",
        timestamp="2026-10-01T00:00:00+00:00",
        input_artifacts=("example-raw-v1",),
        output_artifacts=("example-prepared-v1",),
        message="example prepare completed",
    )
    assert ExecutionRecord.from_dict(json.loads(record.to_json())) == record
    assert record.benchmark == "example"
    assert record.inputs == ("example-raw-v1",)
    assert record.outputs == ("example-prepared-v1",)


def test_executor_record_generation():
    result = run_stage("example", "prepare", record=True)
    execution = result["execution"]
    assert execution["benchmark_id"] == "example"
    assert execution["stage"] == "prepare"
    assert execution["input_artifacts"] == ["example-raw-v1"]
    assert execution["output_artifacts"] == ["example-prepared-v1"]
    path = result["execution_path"]
    assert path.startswith("runs/example-prepare-")
    assert path.endswith(".json")
    stored = json.loads(Path(path).read_text())
    assert stored == execution


def test_executor_accepts_benchmark_keyword_alias():
    result = run_stage(benchmark="example", stage="prepare")
    assert result["status"] == "PASS"


def test_cli_record(capsys):
    assert main(["run", "example", "--stage", "prepare", "--record"]) == 0
    output = capsys.readouterr().out
    assert "Execution record: runs/example-prepare-" in output
