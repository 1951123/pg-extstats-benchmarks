import json
import pytest

from pgextstats_benchmarks.instances import LoadedInstance
from pgextstats_benchmarks.validation import ValidationCheck, ValidationReport
from pgextstats_benchmarks.validators import BenchmarkValidator
from pgextstats_benchmarks.validator_registry import get_validator, list_validators
from pgextstats_benchmarks.example_validator import ExampleValidator


def test_validation_check_serialization():
    check = ValidationCheck(
        name="instance_exists",
        status="PASS",
        expected=True,
        actual=True,
        message="instance metadata is present",
    )
    assert ValidationCheck.from_dict(json.loads(json.dumps(check.to_dict()))) == check


def test_validation_report_serialization():
    report = ValidationReport(
        benchmark_id="example",
        instance_id="example-memory-v1",
        status="PASS",
        checks=(ValidationCheck("instance_exists", "PASS"),),
        metadata={"validator": "ExampleValidator"},
    )
    assert ValidationReport.from_dict(json.loads(report.to_json())) == report


def test_validator_registry_and_abstract_contract():
    assert "example-validator" in list_validators()
    assert get_validator("example-validator") is ExampleValidator
    with pytest.raises(ValueError, match="No validator"):
        get_validator("missing")
    with pytest.raises(TypeError):
        BenchmarkValidator()


def test_example_validator_pass_and_fail():
    validator = ExampleValidator()
    ready = LoadedInstance("example-memory-v1", "example", "ExampleMemoryLoader", "READY")
    report = validator.validate_instance(ready)
    assert report.status == "PASS"
    assert [check.name for check in report.checks] == [
        "instance_exists", "instance_status_ready"
    ]
    not_ready = LoadedInstance("example-memory-v1", "example", "ExampleMemoryLoader", "NEW")
    assert validator.validate_instance(not_ready).status == "FAIL"
