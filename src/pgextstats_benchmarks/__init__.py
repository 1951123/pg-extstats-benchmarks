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

# Importing these modules performs the explicit toy registrations. There is
# no dynamic discovery; the example implementations are the only built-ins.
from .example_adapter import ExampleAdapter
from .example_loader import ExampleMemoryLoader
from .example_validator import ExampleValidator

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
    "LoadedInstance",
    "Lineage",
    "ValidationCheck",
    "ValidationReport",
]
