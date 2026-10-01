"""Benchmark infrastructure and the explicitly registered built-in toy adapter."""
__version__ = "0.1.0"

# Importing the package performs the one explicit built-in registration. There
# is no dynamic adapter discovery.
from .example_adapter import ExampleAdapter  # noqa: E402,F401
