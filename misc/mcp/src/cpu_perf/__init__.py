"""cpu-perf: the CPU Performance Engineering list as an MCP server."""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("cpu-perf")
    except PackageNotFoundError:  # running from a checkout without an install
        __version__ = "0+checkout"
except ImportError:  # pragma: no cover
    __version__ = "0+checkout"

REPO_URL = "https://github.com/usamahz/cpu-performance-engineering"
