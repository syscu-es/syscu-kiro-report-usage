"""Kiro usage and cost report generator."""

from importlib.metadata import PackageNotFoundError, version

try:
    # single source of truth: the version declared in pyproject.toml
    __version__ = version("syscu-kiro-report-usage")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
