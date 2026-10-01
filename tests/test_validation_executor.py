from pgextstats_benchmarks.cli import main
from pgextstats_benchmarks.executor import load_artifact, validate_instance
from pgextstats_benchmarks.instances import LoadedInstance


def test_executor_validation_integration():
    loaded = load_artifact("example", "example-memory")
    instance = LoadedInstance.from_dict(loaded["instance"])
    result = validate_instance("example", instance, "example-validator")
    assert result["validator"] == "ExampleValidator"
    assert result["status"] == "PASS"
    assert result["report"]["instance_id"] == "example-memory-v1"


def test_cli_validator_commands(capsys):
    assert main(["validators"]) == 0
    assert "example-validator" in capsys.readouterr().out
    assert main(["validate-example"]) == 0
    output = capsys.readouterr().out
    assert "Validator: ExampleValidator" in output
    assert "Instance: example-memory-v1" in output
    assert "Status: PASS" in output
    assert "instance_exists PASS" in output
    assert "instance_ready PASS" in output
