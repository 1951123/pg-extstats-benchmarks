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

# Importing these modules performs the explicit toy registrations. There is
# no dynamic discovery; the example implementations are the only built-ins.
from .example_adapter import ExampleAdapter
from .example_loader import ExampleMemoryLoader
from .example_validator import ExampleValidator
from .census_adapter import CensusAdapter
from .census_validator import CensusValidator
from .census_validator import CensusTruthValidator
from .postgres import PostgresConnection, PostgresInstance, PostgreSQLLoader
from .postgres import PostgreSQLAnalyzeSampleProvider, SampleReplayResult

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
    "PostgreSQLAnalyzeSampleProvider",
    "SampleReplayResult",
]
