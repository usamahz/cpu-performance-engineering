"""Bundle the repository's files into the wheel and sdist, so an installed
server works without a checkout.

* Building from the source tree (uv, pip, `uv build --wheel`): the files
  listed by src/cpu_perf/manifest.py are force-included from the
  repository root two levels up.
* Building a wheel from an unpacked sdist: the sdist already carries the files
  under src/cpu_perf/corpus/, so nothing is added.
* Editable installs read the checkout directly.

Nothing is ever written into the working tree; the provenance file is
written to a temporary directory. The source library (crawled text) is never
bundled."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _load_manifest(project: Path):
    path = project / "src" / "cpu_perf" / "manifest.py"
    spec = importlib.util.spec_from_file_location("_cpu_perf_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CorpusBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name not in ("wheel", "sdist") or version == "editable":
            return
        project = Path(self.root).resolve()
        manifest = _load_manifest(project)
        bundled = project / "src" / "cpu_perf" / "corpus"
        repo = manifest.find_repo(project, os.environ.get("CPU_PERF_CORPUS_ROOT"))
        if repo is None:
            if (bundled / "README.md").is_file():
                return  # a wheel built from an unpacked sdist: the corpus is already inside
            raise RuntimeError(
                "cpu-perf: the repository files were not found two levels above misc/mcp. "
                "Build from a full checkout (uv, or pip 21.3+ which builds in place), or set "
                "CPU_PERF_CORPUS_ROOT to the repository root."
            )
        if bundled.exists():
            raise RuntimeError(f"cpu-perf: remove the stray {bundled} before building from the repository")
        files = manifest.select(repo)
        if "README.md" not in files:
            raise RuntimeError(f"cpu-perf: {repo} has no README.md")
        prefix = "cpu_perf/corpus" if self.target_name == "wheel" else "src/cpu_perf/corpus"
        for rel in files:
            build_data["force_include"][str(repo / rel)] = f"{prefix}/{rel}"
        self._tmp = tempfile.TemporaryDirectory(prefix="cpu-perf-build-")
        info = Path(self._tmp.name) / "_build_info.json"
        info.write_text(manifest.dumps(manifest.build_info(repo, files)), encoding="utf-8")
        build_data["force_include"][str(info)] = f"{prefix}/_build_info.json"

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()
            self._tmp = None
