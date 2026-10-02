"""Read-only CLI skeleton."""
import argparse
import os
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
from .statistics_configuration import StatisticsConfiguration
from .statistics_configuration_validator import StatisticsConfigurationValidator
from .estimate_validator import EstimateArtifactValidator
from .evaluation import ArtifactEvaluator, truth_digest
from .evaluation_storage import (
    allocate_evaluation_artifact_dir,
    load_evaluation_artifact,
    write_evaluation_artifact,
)
from .evaluation_validator import EvaluationArtifactValidator
from .estimate_storage import load_estimate_artifact
from .truth_storage import load_truth_artifact
from .experiment import ExperimentRunArtifact
from .experiment_storage import (
    allocate_experiment_artifact_dir,
    load_experiment_artifact,
    write_experiment_artifact,
)
from .experiment_validator import ExperimentRunArtifactValidator
from .comparison import ComparisonReport
from .comparison_storage import (
    allocate_comparison_report_dir,
    write_comparison_report,
)
from .comparison_validator import ComparisonReportValidator
from .statistics_storage import load_repository_artifact
from .workload_executor import load_workload_artifact
from .postgres.statistics_provider import PostgreSQLStatisticsRepositoryProvider
from .postgres.estimate_provider import PostgreSQLEstimateProvider
from .postgres.instance import PostgresInstance
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
    config_validate = commands.add_parser("configuration-validate")
    config_validate.add_argument("benchmark")
    config_validate.add_argument("repository_artifact")
    config_validate.add_argument("configuration", type=Path)
    estimate = commands.add_parser("estimate-collect")
    estimate.add_argument("benchmark")
    estimate.add_argument("workload_artifact")
    estimate.add_argument("repository_artifact")
    estimate.add_argument("configuration", type=Path)
    estimate.add_argument("--database", default=os.environ.get("PGEXTBENCH_DATABASE"))
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("benchmark")
    evaluate.add_argument("truth_artifact")
    evaluate.add_argument("estimate_artifact")
    experiment_create = commands.add_parser("experiment-create")
    experiment_create.add_argument("benchmark")
    experiment_create.add_argument("--baseline", required=True)
    experiment_create.add_argument("evaluation_artifacts", nargs="+")
    comparison_report = commands.add_parser("comparison-report")
    comparison_report.add_argument("benchmark")
    comparison_report.add_argument("experiment_artifact")
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
        elif args.command == "configuration-validate":
            root = benchmark_data_root()
            repository = load_repository_artifact(args.benchmark, args.repository_artifact, root)
            configuration = StatisticsConfiguration.from_file(str(args.configuration))
            report = StatisticsConfigurationValidator().validate(configuration, repository)
            print(f"Benchmark: {args.benchmark}")
            print(f"Repository: {repository.artifact_id}")
            print(f"Configuration: {configuration.configuration_id}")
            print(f"Selected candidates: {configuration.selected_candidate_count}")
            print(f"Status: {report.status}")
            return 0 if report.status == "PASS" else 1
        elif args.command == "estimate-collect":
            if not args.database:
                raise ValueError("estimate-collect requires --database or PGEXTBENCH_DATABASE")
            root = benchmark_data_root()
            repository = load_repository_artifact(args.benchmark, args.repository_artifact, root)
            configuration = StatisticsConfiguration.from_file(str(args.configuration))
            workload_path = root / args.benchmark / "artifacts" / args.workload_artifact
            workload = load_workload_artifact(workload_path)
            instance = PostgresInstance(args.database, args.database, "READY")
            provider = PostgreSQLEstimateProvider()
            try:
                result = provider.collect(
                    instance, workload, repository, configuration,
                    benchmark_id=args.benchmark, root=root,
                )
                artifact = result["artifact"]
                report = EstimateArtifactValidator().validate(
                    artifact, workload=workload, repository=repository, configuration=configuration,
                )
                repo_root = Path(__file__).resolve().parents[2]
                execution = ExecutionRecord(
                    execution_id=new_execution_id(), benchmark_id=args.benchmark,
                    stage="estimate_collect", operation="estimate_collect",
                    status="PASS" if report.status == "PASS" else result["status"],
                    repository_commit=repository_commit(repo_root), timestamp=datetime.now(timezone.utc).isoformat(),
                    input_artifacts=(workload.workload_id, repository.artifact_id, configuration.configuration_id),
                    output_artifacts=(artifact.artifact_id,), message=result["message"],
                    metadata={
                        "workload_digest": artifact.workload_digest,
                        "repository_digest": artifact.repository_digest,
                        "configuration_digest": artifact.configuration_digest,
                        "query_count": artifact.query_count,
                        "successful_count": artifact.successful_count,
                        "unsupported_count": result["unsupported_count"],
                        "failed_count": artifact.failed_count,
                        "postgres_source_commit": artifact.postgres_source["source_commit"],
                        "estimate_digest": artifact.estimate_digest,
                    },
                )
                execution_path = write_execution_record(execution, repo_root)
                print(f"Benchmark: {args.benchmark}")
                print(f"Workload: {workload.workload_id}")
                print(f"Repository digest: {repository.repository_digest}")
                print(f"Configuration: {configuration.configuration_id}")
                print(f"Configuration digest: {configuration.configuration_digest}")
                print(f"Selected candidates: {configuration.selected_candidate_count}")
                print(f"Queries: {artifact.query_count}")
                print(f"PASS: {artifact.successful_count}")
                print(f"UNSUPPORTED: {result['unsupported_count']}")
                print(f"ERROR: {artifact.failed_count}")
                print(f"Estimate artifact: {artifact.artifact_id}")
                print(f"Estimate digest: {artifact.estimate_digest}")
                print(f"PostgreSQL source commit: {artifact.postgres_source['source_commit']}")
                print(f"Execution record: {execution_path}")
                print(f"Status: {execution.status}")
                return 0 if execution.status == "PASS" else 1
            finally:
                provider.close()
        elif args.command == "evaluate":
            root = benchmark_data_root()
            truth = load_truth_artifact(args.benchmark, args.truth_artifact, root)
            estimate_artifact = load_estimate_artifact(args.benchmark, args.estimate_artifact, root)
            artifact_id = f"evaluation-{args.truth_artifact}-{args.estimate_artifact}"
            evaluator = ArtifactEvaluator()
            evaluation = evaluator.evaluate(
                truth,
                estimate_artifact,
                truth_artifact_id=args.truth_artifact,
                truth_digest_value=truth_digest(truth),
                artifact_id=artifact_id,
            )
            directory = allocate_evaluation_artifact_dir(args.benchmark, evaluation.artifact_id, root)
            write_evaluation_artifact(evaluation, root)
            report = EvaluationArtifactValidator().validate(
                evaluation, truth=truth, estimate=estimate_artifact,
            )
            repo_root = Path(__file__).resolve().parents[2]
            execution = ExecutionRecord(
                execution_id=new_execution_id(), benchmark_id=args.benchmark,
                stage="evaluation_compute", operation="evaluation_compute",
                status=report.status,
                repository_commit=repository_commit(repo_root),
                timestamp=datetime.now(timezone.utc).isoformat(),
                input_artifacts=(args.truth_artifact, args.estimate_artifact),
                output_artifacts=(evaluation.artifact_id,),
                message="Offline truth-versus-estimate evaluation completed",
                metadata={
                    "workload_id": evaluation.workload_id,
                    "workload_digest": evaluation.workload_digest,
                    "truth_artifact_id": evaluation.truth_artifact_id,
                    "truth_digest": evaluation.truth_digest,
                    "estimate_artifact_id": evaluation.estimate_artifact_id,
                    "estimate_digest": evaluation.estimate_digest,
                    "repository_artifact_id": evaluation.repository_artifact_id,
                    "repository_digest": evaluation.repository_digest,
                    "configuration_id": evaluation.configuration_id,
                    "configuration_digest": evaluation.configuration_digest,
                    "successful_count": evaluation.successful_count,
                    "excluded_count": evaluation.excluded_count,
                    "failed_count": evaluation.failed_count,
                    "evaluation_digest": evaluation.evaluation_digest,
                },
            )
            execution_path = write_execution_record(execution, repo_root)
            metrics = evaluation.aggregate_metrics
            print(f"Benchmark: {evaluation.benchmark_id}")
            print(f"Workload: {evaluation.workload_id}")
            print(f"Configuration: {evaluation.configuration_id}")
            print(f"PASS: {evaluation.successful_count}")
            print(f"EXCLUDED: {evaluation.excluded_count}")
            print(f"ERROR: {evaluation.failed_count}")
            print(f"Mean q-error: {metrics['mean_q_error']}")
            print(f"Median q-error: {metrics['median_q_error']}")
            print(f"P90 q-error: {metrics['p90_q_error']}")
            print(f"P95 q-error: {metrics['p95_q_error']}")
            print(f"Max q-error: {metrics['max_q_error']}")
            print(f"Evaluation artifact: {evaluation.artifact_id}")
            print(f"Evaluation digest: {evaluation.evaluation_digest}")
            print(f"Artifact directory: {directory}")
            print(f"Execution record: {execution_path}")
            print(f"Status: {report.status}")
            return 0 if report.status == "PASS" else 1
        elif args.command == "experiment-create":
            root = benchmark_data_root()
            evaluations = tuple(
                load_evaluation_artifact(args.benchmark, artifact_id, root)
                for artifact_id in args.evaluation_artifacts
            )
            repositories = {
                evaluation.repository_artifact_id: load_repository_artifact(
                    args.benchmark, evaluation.repository_artifact_id, root
                )
                for evaluation in evaluations
            }
            experiment_id = f"{args.benchmark}-experiment-{args.baseline}"
            labels = {evaluation.artifact_id: evaluation.artifact_id for evaluation in evaluations}
            experiment = ExperimentRunArtifact.from_evaluations(
                experiment_id=experiment_id,
                evaluations=evaluations,
                repositories=repositories,
                baseline_label=args.baseline,
                labels=labels,
            )
            validation = ExperimentRunArtifactValidator().validate(
                experiment, evaluations=evaluations, repositories=repositories,
            )
            if validation.status != "PASS":
                raise ValueError("experiment comparability validation failed")
            directory = allocate_experiment_artifact_dir(args.benchmark, experiment.experiment_id, root)
            write_experiment_artifact(experiment, root)
            repo_root = Path(__file__).resolve().parents[2]
            execution = ExecutionRecord(
                execution_id=new_execution_id(), benchmark_id=args.benchmark,
                stage="experiment_run_create", operation="experiment_run_create", status="PASS",
                repository_commit=repository_commit(repo_root), timestamp=datetime.now(timezone.utc).isoformat(),
                input_artifacts=tuple(item.artifact_id for item in evaluations),
                output_artifacts=(experiment.experiment_id,), message="Experiment run artifact created",
                metadata={
                    "workload_id": experiment.workload_id,
                    "workload_digest": experiment.workload_digest,
                    "truth_digest": experiment.truth_digest,
                    "sample_artifact_id": experiment.sample_artifact_id,
                    "sample_payload_sha256": experiment.sample_payload_sha256,
                    "statistics_repository_digest": experiment.statistics_repository_digest,
                    "postgres_source_commit": experiment.postgres_source["source_commit"],
                    "configuration_count": len(experiment.evaluations),
                    "baseline_configuration_id": experiment.baseline_configuration_id,
                    "experiment_digest": experiment.experiment_digest,
                },
            )
            execution_path = write_execution_record(execution, repo_root)
            print(f"Benchmark: {experiment.benchmark_id}")
            print(f"Workload: {experiment.workload_id}")
            print(f"Truth digest: {experiment.truth_digest}")
            print(f"Sample artifact: {experiment.sample_artifact_id}")
            print(f"Repository artifact: {experiment.statistics_repository_artifact_id}")
            print(f"PostgreSQL source commit: {experiment.postgres_source['source_commit']}")
            print(f"Baseline configuration: {experiment.baseline_configuration_id}")
            print(f"Configuration count: {len(experiment.evaluations)}")
            print(f"Experiment artifact: {experiment.experiment_id}")
            print(f"Experiment digest: {experiment.experiment_digest}")
            print(f"Artifact directory: {directory}")
            print(f"Execution record: {execution_path}")
            return 0
        elif args.command == "comparison-report":
            root = benchmark_data_root()
            experiment = load_experiment_artifact(args.benchmark, args.experiment_artifact, root)
            evaluations = tuple(
                load_evaluation_artifact(args.benchmark, entry.evaluation_artifact_id, root)
                for entry in experiment.evaluations
            )
            report_id = f"{experiment.experiment_id}-comparison"
            report = ComparisonReport.create(
                report_id=report_id, experiment=experiment, evaluations=evaluations,
            )
            validation = ComparisonReportValidator().validate(
                report, experiment=experiment, evaluations=evaluations,
            )
            if validation.status != "PASS":
                raise ValueError("comparison report validation failed")
            directory = allocate_comparison_report_dir(args.benchmark, report.report_id, root)
            write_comparison_report(report, args.benchmark, root)
            repo_root = Path(__file__).resolve().parents[2]
            execution = ExecutionRecord(
                execution_id=new_execution_id(), benchmark_id=args.benchmark,
                stage="comparison_report_create", operation="comparison_report_create", status="PASS",
                repository_commit=repository_commit(repo_root), timestamp=datetime.now(timezone.utc).isoformat(),
                input_artifacts=(experiment.experiment_id,), output_artifacts=(report.report_id,),
                message="Descriptive comparison report created",
                metadata={
                    "experiment_digest": report.experiment_digest,
                    "configuration_count": len(report.configuration_summaries),
                    "baseline_configuration_id": report.baseline_configuration_id,
                    "report_digest": report.report_digest,
                },
            )
            execution_path = write_execution_record(execution, repo_root)
            print(f"Experiment: {report.experiment_id}")
            print(f"Baseline configuration: {report.baseline_configuration_id}")
            for summary in report.configuration_summaries:
                metrics = summary.qerror_metrics
                comparison = summary.baseline_comparison
                print(f"Configuration: {summary.configuration_id}")
                print(f"  Mean q-error: {metrics.get('mean_q_error')}")
                print(f"  Median q-error: {metrics.get('median_q_error')}")
                print(f"  P90 q-error: {metrics.get('p90_q_error')}")
                print(f"  P95 q-error: {metrics.get('p95_q_error')}")
                print(f"  Max q-error: {metrics.get('max_q_error')}")
                print(f"  Comparable queries: {comparison.get('comparable_query_count')}")
                print(f"  Improved: {comparison.get('improved_query_count')}")
                print(f"  Unchanged: {comparison.get('unchanged_query_count')}")
                print(f"  Worsened: {comparison.get('worsened_query_count')}")
            print(f"Report artifact: {report.report_id}")
            print(f"Report digest: {report.report_digest}")
            print(f"Artifact directory: {directory}")
            print(f"Execution record: {execution_path}")
            return 0
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
                if result.source_manifest_exists:
                    source_label = "PASS" if result.source_declaration_valid else "FAIL"
                    print(f"Source declaration: {source_label} ({result.source_declaration_status})")
                else:
                    print("Source declaration: FAIL")
                if result.artifact_declarations_present:
                    print(f"Raw artifact: {result.raw_artifact_status}")
                    print(f"Prepared artifact: {result.prepared_artifact_status}")
                    print(f"Workload artifact: {result.workload_artifact_status}")
                else:
                    # Preserve the legacy placeholder output for benchmarks
                    # that do not yet declare materialized artifacts.
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
