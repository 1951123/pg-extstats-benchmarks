"""Compatibility import for the PostgreSQL estimate provider."""
from .estimate_provider import PostgreSQLEstimateProvider, extract_plan_rows

__all__ = ["PostgreSQLEstimateProvider", "extract_plan_rows"]
