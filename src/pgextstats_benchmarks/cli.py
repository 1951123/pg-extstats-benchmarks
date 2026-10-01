"""Read-only CLI skeleton."""
import argparse
from pathlib import Path
import sys
import yaml
from .paths import benchmark_data_root
from .registry import load_registry, verify_benchmark
from .executor import load_artifact, run_stage, validate_instance
from .instances import LoadedInstance
from .loader_registry import list_loaders
from .validator_registry import list_validators


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pgextbench")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("list")
    verify = commands.add_parser("verify")
    verify.add_argument("benchmark")
    run = commands.add_parser("run")
    run.add_argument("benchmark")
    run.add_argument("--stage", required=True)
    run.add_argument("--record", action="store_true")
    commands.add_parser("loaders")
    commands.add_parser("load-example")
    commands.add_parser("validators")
    commands.add_parser("validate-example")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print(f"Data root: {benchmark_data_root()}")
        elif args.command == "loaders":
            for loader_id in list_loaders():
                print(loader_id)
        elif args.command == "load-example":
            result = load_artifact("example", "example-memory")
            print(f"Loader: {result['loader']}")
            print(f"Instance: {result['instance']['instance_id']}")
            print(f"Status: {result['instance']['status']}")
        elif args.command == "validators":
            for validator_id in list_validators():
                print(validator_id)
        elif args.command == "validate-example":
            loaded = load_artifact("example", "example-memory")
            instance = LoadedInstance.from_dict(loaded["instance"])
            result = validate_instance("example", instance, "example-validator")
            print(f"Validator: {result['validator']}")
            print(f"Instance: {result['instance']['instance_id']}")
            print(f"Status: {result['status']}")
            print("Checks:")
            for check in result["report"]["checks"]:
                name = check["name"].replace("instance_status_", "instance_")
                print(f"  {name} {check['status']}")
        elif args.command == "run":
            result = run_stage(args.benchmark, args.stage, record=args.record)
            print(f"Benchmark: {result['benchmark_id']}")
            print(f"Adapter: {result['adapter']}")
            print(f"Stage: {result['stage']}")
            print(f"Status: {result['status']}")
            print(f"Message: {result['message']}")
            if args.record:
                print(f"Execution record: {result['execution_path']}")
        else:
            registry = load_registry(args.repo)
            if args.command == "list":
                for benchmark in registry.values():
                    print(f"{benchmark.id}\t{benchmark.version}\t{benchmark.status}")
            else:
                result = verify_benchmark(args.repo, args.benchmark)
                print(f"Benchmark: {result.benchmark.id}")
                print(f"Directory: {'PASS' if result.directory_exists else 'FAIL'}")
                print(f"Manifest: {'PASS' if result.manifest_exists else 'FAIL'}")
                print(
                    "Source declaration: "
                    f"{'PASS' if result.source_manifest_exists else 'FAIL'}"
                )
                print(f"Raw data: {'PRESENT' if result.raw_data_present else 'NOT PRESENT'}")
                print(f"Status: {result.status}")
                if result.configuration_missing:
                    return 1
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"pgextbench: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
