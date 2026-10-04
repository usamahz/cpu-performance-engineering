"""Which repository files make up the corpus, and where the repository is.

Standard library only and free of package imports: the build hook loads this
file by path before the package exists, and the runtime uses the same
allowlist, so the wheel and a checkout always serve the same files.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

INCLUDE = (
    "README.md",
    "CONTRIBUTING.md",
    "LICENSE",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/*.md",
    "misc/README.md",
    "misc/notes/*.md",
    "misc/notes/sections/[0-9][0-9]-*.md",
    "misc/notes/banner/README.md",
    "misc/benchmarks/README.md",
    "misc/benchmarks/compile_all.sh",
    "misc/benchmarks/run_all.sh",
    "misc/benchmarks/common/*.h",
    "misc/benchmarks/common/*.c",
    "misc/benchmarks/common/*.sh",
    "misc/benchmarks/common/*.py",
    "misc/benchmarks/[0-9][0-9]-*/README.md",
    "misc/benchmarks/[0-9][0-9]-*/bench.c",
    "misc/benchmarks/[0-9][0-9]-*/build.sh",
    "misc/benchmarks/[0-9][0-9]-*/run.sh",
    "misc/benchmarks/[0-9][0-9]-*/results/raw.txt",
    "misc/benchmarks/[0-9][0-9]-*/results/summary.md",
    "misc/scripts/*.py",
)

# Never served even if a pattern above would match them.
EXCLUDE_PARTS = ("misc/mcp/", "/results/quick-", "__pycache__")


def select(root: Path) -> list[str]:
    """Repository-relative POSIX paths of every corpus file under `root`."""
    root = Path(root)
    found: set[str] = set()
    for pattern in INCLUDE:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if any(part in rel for part in EXCLUDE_PARTS):
                continue
            found.add(rel)
    return sorted(found)


def _glob_regex(pattern: str):
    """A path glob as a regex: '*' and '?' never cross '/', like Path.glob."""
    import re

    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[":
            j = pattern.index("]", i)
            out.append("[" + pattern[i + 1 : j].replace("\\", "\\\\") + "]")
            i = j
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z")


_PATTERNS: list = []


def matches(rel: str) -> bool:
    """Whether a repository-relative path belongs to the corpus (what select() would pick)."""
    if not _PATTERNS:
        _PATTERNS.extend(_glob_regex(p) for p in INCLUDE)
    if any(part in rel for part in EXCLUDE_PARTS):
        return False
    return any(p.match(rel) for p in _PATTERNS)


def commit_date(repo: Path) -> str | None:
    """The commit's date (ISO 8601), for choosing the newer of two copies of the list."""
    env = os.environ.get("CPU_PERF_COMMIT_DATE")
    if env:
        return env
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%cI"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def is_repo_root(path: Path) -> bool:
    return (path / "README.md").is_file() and (path / "misc" / "benchmarks").is_dir()


def find_repo(project: Path, override: str | None = None) -> Path | None:
    """The repository root for the project at `project` (misc/mcp), or None.

    `override` (CPU_PERF_CORPUS_ROOT) wins when it names a repository."""
    if override:
        candidate = Path(override).resolve()
        return candidate if is_repo_root(candidate) else None
    project = Path(project).resolve()
    if len(project.parents) < 2:
        return None
    candidate = project.parents[1]
    if not is_repo_root(candidate):
        return None
    if (candidate / "misc" / "mcp").resolve() != project:
        return None
    return candidate


def git_head(repo: Path) -> str | None:
    """The checked-out commit, read from .git without running git."""
    git = Path(repo) / ".git"
    try:
        if git.is_file():  # worktree or submodule: "gitdir: <path>"
            text = git.read_text(encoding="utf-8").strip()
            if text.startswith("gitdir:"):
                git = (Path(repo) / text.split(":", 1)[1].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head.split(":", 1)[1].strip()
        ref_file = git / ref
        if ref_file.is_file():
            return ref_file.read_text(encoding="utf-8").strip() or None
        common = git
        commondir = git / "commondir"
        if commondir.is_file():
            common = (git / commondir.read_text(encoding="utf-8").strip()).resolve()
            if (common / ref).is_file():
                return (common / ref).read_text(encoding="utf-8").strip() or None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        return None
    return None


def build_info(repo: Path, files: list[str]) -> dict:
    """Provenance written next to a bundled corpus."""
    commit = os.environ.get("CPU_PERF_COMMIT") or os.environ.get("GITHUB_SHA") or git_head(repo)
    digests = {}
    for rel in files:
        digests[rel] = hashlib.sha256((Path(repo) / rel).read_bytes()).hexdigest()
    return {
        "commit": commit,
        "commit_date": commit_date(repo),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files,
        "sha256": digests,
    }


def dumps(info: dict) -> str:
    return json.dumps(info, indent=1, sort_keys=True)
