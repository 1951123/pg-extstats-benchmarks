"""Public workload model compatibility module."""

from .workload_executor import Query, Workload, load_workload_artifact, normalize_workload

__all__ = ["Query", "Workload", "load_workload_artifact", "normalize_workload"]
