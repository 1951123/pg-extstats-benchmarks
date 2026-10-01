from pgextstats_benchmarks.cli import main
from pgextstats_benchmarks.executor import load_artifact


def test_executor_loader_integration():
    result = load_artifact("example", "example-memory")
    assert result["loader"] == "ExampleMemoryLoader"
    assert result["artifact_ids"] == ["example-prepared-v1"]
    assert result["instance"]["instance_id"] == "example-memory-v1"
    assert result["instance"]["status"] == "READY"
    assert result["status"] == "PASS"


def test_cli_loader_listing_and_example(capsys):
    assert main(["loaders"]) == 0
    assert "example-memory" in capsys.readouterr().out
    assert main(["load-example"]) == 0
    output = capsys.readouterr().out
    assert "Loader: ExampleMemoryLoader" in output
    assert "Instance: example-memory-v1" in output
    assert "Status: READY" in output


def test_cli_invalid_loader_is_nonzero(capsys):
    assert main(["load-example", "--loader", "missing-loader"]) == 1
    assert "No loader registered" in capsys.readouterr().err
