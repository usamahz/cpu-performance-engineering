"""The MCP Registry listing: server.json agrees with the package, and the
README carries the line the registry looks for on PyPI."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None

HERE = Path(__file__).resolve().parent.parent
SERVER_JSON = HERE / "server.json"
SERVER_NAME_CHAR = re.compile(r"[A-Za-z0-9._/-]")

pytestmark = pytest.mark.skipif(not SERVER_JSON.is_file(), reason="run from the repository, not an installed wheel")


@pytest.fixture(scope="module")
def server():
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


def test_server_json_matches_the_package(server):
    text = (HERE / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib is not None:
        project = tomllib.loads(text)["project"]
        name, version = project["name"], project["version"]
    else:
        name = re.search(r'^name = "([^"]+)"', text, re.M).group(1)
        version = re.search(r'^version = "([^"]+)"', text, re.M).group(1)
    assert server["name"] == "io.github.usamahz/cpu-perf"
    assert server["version"] == version
    (pkg,) = server["packages"]
    assert pkg["registryType"] == "pypi" and pkg["identifier"] == name and pkg["version"] == version
    assert pkg["transport"] == {"type": "stdio"}


def test_server_json_meets_the_registry_rules(server):
    assert 1 <= len(server["description"]) <= 100
    assert 1 <= len(server.get("title", "x")) <= 100
    assert re.fullmatch(r"[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+", server["name"])
    repo = server["repository"]
    assert re.fullmatch(r"https?://(www\.)?github\.com/[\w.-]+/[\w.-]+/?", repo["url"])  # no path: that is subfolder
    assert repo["subfolder"] == "misc/mcp" and not repo["subfolder"].startswith("/")
    assert server["websiteUrl"].startswith("https://")


def test_readme_proves_the_package_is_ours(server):
    """The registry reads the README on PyPI for `mcp-name: <name>` followed by
    a character that cannot continue a server name."""
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    token = "mcp-name: " + server["name"]
    ends = [m.end() for m in re.finditer(re.escape(token), readme)]
    assert any(e == len(readme) or not SERVER_NAME_CHAR.match(readme[e]) for e in ends), token
