"""Read-only CLI skeleton."""
import argparse
from pathlib import Path
import sys
import yaml
from .paths import benchmark_data_root
from .registry import load_registry, verify_benchmark
from .adapters import get_adapter
from .executor import load_artifact, run_stage, validate_instance
from .instances import LoadedInstance
from .loader_registry import get_loader, list_loaders
from .validator_registry import list_validators
from .census_adapter import CensusAdapter
from .census_validator import CensusValidator
from .census_validator import CensusTruthValidator
from .postgres.query_runner import PostgreSQLQueryRunner
from .postgres.sample_provider import PostgreSQLAnalyzeSampleProvider
from .sample_storage import load_sample_manifest
from .candidate_catalog import CandidateCatalog
from .statistics_repository_validator import StatisticsRepositoryValidator
from .postgres.statistics_provider import PostgreSQLStatisticsRepositoryProvider
from .execution import ExecutionRecord, new_execution_id, repository_commit, write_execution_record
from datetime import datetime, timezone


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pgextbench")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("list")
    commands.add_parser("benchmarks")
    verify = commands.add_parser("verify")
    verify.add_argument("benchmark")
    run = commands.add_parser("run")
    run.add_argument("benchmark")
    run.add_argument("--stage", required=True)
    run.add_argument("--record", action="store_true")
    commands.add_parser("loaders")
    commands.add_parser("postgres-check")
    commands.add_parser("load-example-postgres")
    commands.add_parser("load-census-postgres")
    commands.add_parser("collect-census-truth")
    sample_capture = commands.add_parser("sample-capture")
    sample_capture.add_argument("benchmark")
    sample_replay = commands.add_parser("sample-replay")
    sample_replay.add_argument("benchmark")
    sample_replay.add_argument("sample_artifact")
    statistics = commands.add_parser("statistics-acquire")
    statistics.add_argument("benchmark")
    statistics.add_argument("sample_artifact")
    statistics.add_argument("candidate_catalog", type=Path)
    load_example = commands.add_parser("load-example")
    load_example.add_argument("--loader", default="example-memory")
    commands.add_parser("validators")
    validate_example = commands.add_parser("validate-example")
    validate_example.add_argument("--validator", default="example-validator")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print(f"Data root: {benchmark_data_root()}")
        elif args.command == "loaders":
            for loader_id in list_loaders():
                print(loader_id)
        elif args.command == "postgres-check":
            loader = get_loader("postgres")()
            instance = None
            destroyed = False
            try:
                instance = loader.create_instance("test")
                version = str(instance.metadata.get("postgres_version", "unknown"))
                version_parts = version.split()
                display_version = version_parts[1] if len(version_parts) > 1 else version
                print(f"PostgreSQL: {display_version}")
                print(f"Instance: {instance.database_name}")
                print("Create: PASS")
                validation = loader.validate_instance(instance)
                print(f"Validate: {validation['status']}")
                destruction = loader.destroy_instance(instance)
                destroyed = destruction["status"] == "PASS"
                print(f"Destroy: {destruction['status']}")
                return 0 if validation["status"] == "PASS" and destroyed else 1
            finally:
                if instance is not None and not destroyed:
                    try:
                        loader.destroy_instance(instance)
                    except Exception:
                        pass
                loader.close()
        elif args.command == "load-example-postgres":
            result = load_artifact("example", "postgres", destroy=True, record=True)
            instance_metadata = result["instance"].get("metadata", {})
            version = str(instance_metadata.get("postgres_version", "unknown"))
            version_parts = version.split()
            display_version = version_parts[1] if len(version_parts) > 1 else version
            print(f"PostgreSQL: {display_version}")
            print(f"Artifact: {result['artifact_ids'][0]}")
            print(f"Load: {result['load']['status']}")
            print(f"Validation: {result['validation']['status']}")
            print(f"Rows: {instance_metadata.get('rows_loaded', 0)}")
            print(f"Cleanup: {result['cleanup']['status']}")
            return 0 if result["status"] == "PASS" else 1
        elif args.command == "load-census-postgres":
            adapter = CensusAdapter()
            prepared_result = adapter.prepare()
            prepared = prepared_result["output_artifacts"][0]
            raw = prepared_result["input_artifacts"][0]
            workload = adapter.normalize_workload()["output_artifacts"][0]
            loader = get_loader("postgres")()
            instance = None
            destroyed = False
            try:
                instance = loader.create_instance("census")
                loaded = loader.load_artifact(instance, prepared)
                report = CensusValidator().validate_loaded_instance(
                    loaded,
                    loader,
                    raw_artifact=raw,
                    prepared_artifact=prepared,
                    workload_artifact=workload,
                )
                cleanup = loader.destroy_instance(loaded)
                destroyed = cleanup["status"] == "PASS"
                execution = ExecutionRecord(
                    execution_id=new_execution_id(),
                    benchmark_id="census",
                    stage="load",
                    status="PASS" if report.status == "PASS" and destroyed else "FAIL",
                    repository_commit=repository_commit(Path(__file__).resolve().parents[2]),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    input_artifacts=(raw.id, prepared.id, workload.id),
                    output_artifacts=(),
                    message="Census PostgreSQL artifact loading completed",
                    metadata={
                        "artifact_id": prepared.id,
                        "postgres_version": loaded.metadata.get("postgres_version"),
                        "loader_type": loader.__class__.__name__,
                        "instance_metadata": dict(loaded.metadata),
                    },
                )
                write_execution_record(execution, Path(__file__).resolve().parents[2])
                version = str(loaded.metadata.get("postgres_version", "unknown"))
                version_parts = version.split()
                display_version = version_parts[1] if len(version_parts) > 1 else version
                print("Benchmark: census")
                print(f"PostgreSQL: {display_version}")
                print(f"Artifact: {prepared.id}")
                print("Load: PASS")
                print(f"Validation: {report.status}")
                print(f"Rows: {loaded.metadata.get('rows_loaded', 0)}")
                print(f"Cleanup: {cleanup['status']}")
                return 0 if report.status == "PASS" and destroyed else 1
            finally:
                if instance is not None and not destroyed:
                    try:
                        loader.destroy_instance(instance)
                    except Exception:
                        pass
                loader.close()
        elif args.command == "load-example":
            result = load_artifact("example", args.loader)
            print(f"Loader: {result['loader']}")
            print(f"Instance: {result['instance']['instance_id']}")
            print(f"Status: {result['instance']['status']}")
        elif args.command == "collect-census-truth":
            adapter = CensusAdapter()
            prepared_result = adapter.prepare()
            prepared = prepared_result["output_artifacts"][0]
            workload_result = adapter.normalize_workload()
            workload_artifact = workload_result["output_artifacts"][0]
            loader = get_loader("postgres")()
            runner = PostgreSQLQueryRunner()
            instance = None
            destroyed = False
            try:
                instance = loader.create_instance("census")
                loaded = loader.load_artifact(instance, prepared)
                database_validation = loader.validate_instance(loaded)
                if database_validation["status"] != "PASS":
                    raise RuntimeError("Census database validation failed before truth collection")
                truth_result = adapter.collect_truth(loaded, runner)
                truth = truth_result["truth"]
                truth_report = CensusTruthValidator().validate_truth(
                    truth_result["workload"], truth
                )
                cleanup = loader.destroy_instance(loaded)
                destroyed = cleanup["status"] == "PASS"
                repo_root = Path(__file__).resolve().parents[2]
                execution = ExecutionRecord(
                    execution_id=new_execution_id(),
                    benchmark_id="census",
                    stage="collect_truth",
                    status="PASS" if truth_report.status == "PASS" and destroyed else "FAIL",
                    repository_commit=repository_commit(repo_root),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    input_artifacts=(workload_artifact.id,),
                    output_artifacts=(truth_result["output_artifacts"][0].id,),
                    message="Census truth collection completed",
                    metadata={
                        "workload_artifact_id": workload_artifact.id,
                        "postgres_version": loaded.metadata.get("postgres_version"),
                        "query_runner": runner.__class__.__name__,
                        "query_count": truth.query_count,
                        "successful_queries": truth.successful_queries,
                    },
                )
                write_execution_record(execution, repo_root)
                version = str(loaded.metadata.get("postgres_version", "unknown"))
                version_parts = version.split()
                display_version = version_parts[1] if len(version_parts) > 1 else version
                truth_artifact = truth_result["output_artifacts"][0]
                print("Benchmark: census")
                print(f"Workload: {workload_artifact.id}")
                print(f"Runner: {runner.__class__.__name__}")
                print(f"PostgreSQL: {display_version}")
                print(f"Queries: {truth.query_count}")
                print(f"Truth: {truth_report.status}")
                print(f"Truth artifact: {truth_artifact.path / 'truth.json'}")
                print(f"Successful queries: {truth.successful_queries}")
                return 0 if truth_report.status == "PASS" and destroyed else 1
            finally:
                if instance is not None and not destroyed:
                    try:
                        loader.destroy_instance(instance)
                    except Exception:
                        pass
                runner.close()
                loader.close()
        elif args.command in {"sample-capture", "sample-replay"}:
            if args.benchmark != "census":
                raise ValueError("sample commands currently support benchmark: census")
            adapter = CensusAdapter()
            prepared = adapter.prepared_artifact()
            loader = get_loader("postgres")()
            provider = PostgreSQLAnalyzeSampleProvider()
            instance = None
            destroyed = False
            repo_root = Path(__file__).resolve().parents[2]
            try:
                instance = loader.create_instance("census")
                loaded = loader.load_artifact(instance, prepared)
                validation = loader.validate_instance(loaded)
                if validation["status"] != "PASS":
                    raise RuntimeError("managed Census instance validation failed")
                if args.command == "sample-capture":
                    result = provider.capture_sample(
                        loaded,
                        adapter.relation_identity,
                        benchmark_id="census",
                        parent_data_artifact_id=prepared.id,
                        root=adapter.data_root,
                    )
                    artifact = result["artifact"]
                    execution = ExecutionRecord(
                        execution_id=new_execution_id(), benchmark_id="census",
                        stage="sample_capture", operation="sample_capture", status="PASS",
                        repository_commit=repository_commit(repo_root),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        input_artifacts=(prepared.id,), output_artifacts=(artifact.artifact_id,),
                        message=result["message"], metadata={
                            "relation_identity": artifact.relation_identity,
                            "payload_sha256": artifact.payload_sha256,
                            "postgres_source": dict(artifact.postgres_source),
                        },
                    )
                    record_path = write_execution_record(execution, repo_root)
                    cleanup = loader.destroy_instance(loaded)
                    destroyed = cleanup["status"] == "PASS"
                    source = artifact.postgres_source
                    print("Benchmark: census")
                    print(f"Relation: {artifact.relation_identity}")
                    print(f"Sample artifact ID: {artifact.artifact_id}")
                    print(f"Tuple count: {artifact.sample_tuple_count}")
                    print(f"Payload SHA256: {artifact.payload_sha256}")
                    print(f"Artifact directory: {Path(artifact.payload_relative_path).parent}")
                    print(f"PostgreSQL source commit: {source.get('source_commit')}")
                    print(f"Execution record: {record_path}")
                    print(f"Cleanup: {cleanup['status']}")
                    return 0 if destroyed else 1
                artifact = load_sample_manifest("census", args.sample_artifact, adapter.data_root)
                replay = provider.replay_sample(
                    loaded, artifact, relation_identity=adapter.relation_identity, root=adapter.data_root
                )
                execution = ExecutionRecord(
                    execution_id=new_execution_id(), benchmark_id="census",
                    stage="sample_replay", operation="sample_replay", status=replay.status,
                    repository_commit=repository_commit(repo_root),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    input_artifacts=(prepared.id, artifact.artifact_id), output_artifacts=(),
                    message=replay.message, metadata={
                        "relation_identity": replay.relation_identity,
                        "payload_sha256": replay.payload_sha256,
                        "postgres_source": dict(replay.postgres_source),
                    },
                )
                record_path = write_execution_record(execution, repo_root)
                cleanup = loader.destroy_instance(loaded)
                destroyed = cleanup["status"] == "PASS"
                print("Benchmark: census")
                print(f"Relation: {replay.relation_identity}")
                print(f"Sample artifact ID: {replay.artifact_id}")
                print(f"Payload SHA256: {replay.payload_sha256}")
                print(f"PostgreSQL source commit: {replay.postgres_source.get('source_commit')}")
                print(f"Replay: {replay.status}")
                print(f"Execution record: {record_path}")
                print(f"Cleanup: {cleanup['status']}")
                return 0 if replay.status == "PASS" and destroyed else 1
            finally:
                if instance is not None and not destroyed:
                    try:
                        loader.destroy_instance(instance)
                    except Exception:
                        pass
                loader.close()
        elif args.command == "statistics-acquire":
            if not args.benchmark:
                raise ValueError("statistics-acquire requires a benchmark")
            root = benchmark_data_root()
            sample = load_sample_manifest(args.benchmark, args.sample_artifact, root)
            catalog = CandidateCatalog.from_file(args.candidate_catalog)
            if catalog.relation_identity != sample.relation_identity:
                raise ValueError("candidate catalog relation does not match SampleArtifact")
            adapter_class = get_adapter(args.benchmark)
            prepared_result = adapter_class().prepare()
            prepared = prepared_result["output_artifacts"][0]
            loader = get_loader("postgres")()
            provider = PostgreSQLStatisticsRepositoryProvider()
            instance = None
            destroyed = False
            repo_root = Path(__file__).resolve().parents[2]
            try:
                instance = loader.create_instance(args.benchmark)
                loaded = loader.load_artifact(instance, prepared)
                if loader.validate_instance(loaded)["status"] != "PASS":
                    raise RuntimeError("managed benchmark instance validation failed")
                result = provider.acquire_repository(
                    loaded, sample, catalog, benchmark_id=args.benchmark, root=root
                )
                if result["status"] != "PASS":
                    print(f"Benchmark: {args.benchmark}")
                    print(f"Status: FAIL")
                    print(f"Message: {result['message']}")
                    return 1
                artifact = result["artifact"]
                report = StatisticsRepositoryValidator().validate(
                    artifact, sample_artifact=sample, candidate_catalog=catalog, root=root
                )
                cleanup = loader.destroy_instance(loaded)
                destroyed = cleanup["status"] == "PASS"
                execution = ExecutionRecord(
                    execution_id=new_execution_id(), benchmark_id=args.benchmark,
                    stage="statistics_repository_acquire", operation="statistics_repository_acquire",
                    status="PASS" if report.status == "PASS" and destroyed else "FAIL",
                    repository_commit=repository_commit(repo_root),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    input_artifacts=(sample.artifact_id, catalog.catalog_id),
                    output_artifacts=(artifact.artifact_id,),
                    message=result["message"],
                    metadata={
                        "sample_payload_sha256": artifact.sample_payload_sha256,
                        "catalog_sha256": catalog.catalog_sha256,
                        "candidate_count": catalog.candidate_count,
                        "present_count": result["present_count"],
                        "absent_native_count": result["absent_native_count"],
                        "postgres_source_commit": artifact.postgres_source["source_commit"],
                        "statistics_target": artifact.statistics_target,
                        "repository_digest": artifact.repository_digest,
                    },
                )
                execution_path = write_execution_record(execution, repo_root)
                print(f"Benchmark: {args.benchmark}")
                print(f"Relation: {artifact.relation_identity}")
                print(f"SampleArtifact: {artifact.sample_artifact_id}")
                print(f"Candidate catalog SHA256: {catalog.catalog_sha256}")
                print(f"Candidate count: {catalog.candidate_count}")
                print(f"PRESENT: {result['present_count']}")
                print(f"ABSENT_NATIVE: {result['absent_native_count']}")
                print(f"Repository artifact: {artifact.artifact_id}")
                print(f"Repository digest: {artifact.repository_digest}")
                print(f"PostgreSQL source commit: {artifact.postgres_source['source_commit']}")
                print(f"Import count: {result['sample_import_count']}")
                print(f"ANALYZE count: {result['analyze_count']}")
                print(f"Execution record: {execution_path}")
                print(f"Status: {execution.status}")
                return 0 if execution.status == "PASS" else 1
            finally:
                if instance is not None and not destroyed:
                    try:
                        loader.destroy_instance(instance)
                    except Exception:
                        pass
                loader.close()
        elif args.command == "validators":
            for validator_id in list_validators():
                print(validator_id)
        elif args.command == "validate-example":
            loaded = load_artifact("example", "example-memory")
            instance = LoadedInstance.from_dict(loaded["instance"])
            result = validate_instance("example", instance, args.validator)
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
            if args.command in {"list", "benchmarks"}:
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
    except (ValueError, OSError, RuntimeError, yaml.YAMLError) as exc:
        print(f"pgextbench: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
