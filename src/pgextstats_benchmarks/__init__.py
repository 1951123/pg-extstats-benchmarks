"""Public models and contracts for benchmark lifecycle infrastructure."""
__version__ = "0.1.0"

from .adapter import BenchmarkAdapter
from .artifacts import Artifact
from .execution import ExecutionRecord
from .instances import LoadedInstance
from .lineage import Lineage
from .loaders import DatabaseLoader
from .validation import ValidationCheck, ValidationReport
from .validators import BenchmarkValidator
from .query_runner import QueryExecutionResult, QueryRunner
from .truth import TruthArtifact
from .workload_executor import Query, Workload
from .sample_artifacts import SampleArtifact
from .sample_validator import SampleArtifactValidator
from .candidate_catalog import CandidateCatalog, CandidateDefinition
from .statistics_repository import CandidatePayloadState, StatisticsRepositoryArtifact
from .statistics_repository_validator import StatisticsRepositoryValidator
from .statistics_configuration import StatisticsConfiguration
from .statistics_configuration_validator import StatisticsConfigurationValidator
from .estimate import EstimateArtifact, QueryEstimate, workload_digest
from .estimate_validator import EstimateArtifactValidator
from .evaluation import (
    ArtifactEvaluator,
    CardinalityEvaluationProvider,
    EvaluationArtifact,
    QueryEvaluation,
    aggregate_q_errors,
    nearest_rank,
    q_error,
    truth_digest,
    evaluate,
    evaluate_artifacts,
)
from .evaluation_validator import EvaluationArtifactValidator
from .experiment import ExperimentEntry, ExperimentEvaluationEntry, ExperimentRunArtifact
from .experiment_validator import ExperimentRunArtifactValidator
from .comparison import ComparisonReport, ConfigurationSummary, QueryComparison
from .comparison_validator import ComparisonReportValidator

# Importing these modules performs the explicit toy registrations. There is
# no dynamic discovery; the example implementations are the only built-ins.
from .example_adapter import ExampleAdapter
from .example_loader import ExampleMemoryLoader
from .example_validator import ExampleValidator
from .census_adapter import CensusAdapter
from .census_validator import CensusValidator
from .census_validator import CensusTruthValidator
from .postgres import PostgresConnection, PostgresInstance, PostgreSQLLoader
from .postgres import PostgreSQLAnalyzeSampleProvider, SampleReplayResult, PostgreSQLStatisticsRepositoryProvider

__all__ = [
    "__version__",
    "Artifact",
    "BenchmarkAdapter",
    "BenchmarkValidator",
    "DatabaseLoader",
    "ExecutionRecord",
    "ExampleAdapter",
    "ExampleMemoryLoader",
    "ExampleValidator",
    "CensusAdapter",
    "CensusValidator",
    "CensusTruthValidator",
    "LoadedInstance",
    "Lineage",
    "PostgresConnection",
    "PostgresInstance",
    "PostgreSQLLoader",
    "ValidationCheck",
    "ValidationReport",
    "Query",
    "Workload",
    "QueryRunner",
    "QueryExecutionResult",
    "TruthArtifact",
    "SampleArtifact",
    "SampleArtifactValidator",
    "CandidateCatalog",
    "CandidateDefinition",
    "CandidatePayloadState",
    "StatisticsRepositoryArtifact",
    "StatisticsRepositoryValidator",
    "StatisticsConfiguration",
    "StatisticsConfigurationValidator",
    "EstimateArtifact",
    "QueryEstimate",
    "EstimateArtifactValidator",
    "EvaluationArtifact",
    "QueryEvaluation",
    "ArtifactEvaluator",
    "CardinalityEvaluationProvider",
    "EvaluationArtifactValidator",
    "aggregate_q_errors",
    "nearest_rank",
    "q_error",
    "truth_digest",
    "evaluate",
    "evaluate_artifacts",
    "ExperimentEntry",
    "ExperimentEvaluationEntry",
    "ExperimentRunArtifact",
    "ExperimentRunArtifactValidator",
    "ComparisonReport",
    "ConfigurationSummary",
    "QueryComparison",
    "ComparisonReportValidator",
    "workload_digest",
    "PostgreSQLAnalyzeSampleProvider",
    "SampleReplayResult",
    "PostgreSQLStatisticsRepositoryProvider",
]
