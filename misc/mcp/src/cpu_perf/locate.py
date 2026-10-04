"""Find the corpus: an explicit checkout, the checkout this module lives in,
or the copy bundled inside the wheel."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import manifest


class CorpusNotFound(RuntimeError):
    pass


@dataclass
class CorpusReader:
    """Read-only access to an allowlisted set of corpus files."""

    source: str  # "checkout" | "explicit" | "bundled" | "downloaded"
    root: object  # Path or importlib Traversable
    files: list[str]
    commit: str | None = None
    built_at: str | None = None
    commit_date: str | None = None
    _cache: dict[str, str] = field(default_factory=dict, repr=False)

    def has(self, rel: str) -> bool:
        return rel in self._fileset

    @property
    def _fileset(self) -> frozenset[str]:
        fs = self.__dict__.get("_fs")
        if fs is None:
            fs = frozenset(self.files)
            self.__dict__["_fs"] = fs
        return fs

    def read_text(self, rel: str) -> str:
        if rel not in self._fileset:
            raise KeyError(rel)
        text = self._cache.get(rel)
        if text is None:
            node = self.root
            for part in rel.split("/"):
                node = node / part
            raw = node.read_bytes()
            text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
            self._cache[rel] = text
        return text

    def size(self, rel: str) -> int:
        return len(self.read_text(rel).encode("utf-8"))

    def describe(self) -> str:
        where = str(self.root) if self.source != "bundled" else "wheel"
        commit = (self.commit or "unknown")[:12]
        when = f", {self.commit_date[:10]}" if self.commit_date else ""
        return f"{self.source} ({where}, commit {commit}{when})"

    def preload(self) -> None:
        """Read every file now, so the copy on disk can be replaced while serving."""
        for rel in self.files:
            self.read_text(rel)

    @property
    def date_key(self) -> str:
        """Comparable recency: the commit date, else the build time."""
        return _utc(self.commit_date or self.built_at)


def _utc(stamp: str | None) -> str:
    if not stamp:
        return ""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _checkout_root() -> Path | None:
    """The repository root when this module is <root>/misc/mcp/src/cpu_perf/locate.py."""
    here = Path(__file__).resolve()
    pkg = here.parent
    if pkg.name != "cpu_perf" or pkg.parent.name != "src":
        return None
    project = pkg.parent.parent
    if project.name != "mcp" or project.parent.name != "misc":
        return None
    root = project.parent.parent
    return root if manifest.is_repo_root(root) else None


def _from_dir(root: Path, source: str) -> CorpusReader:
    files = manifest.select(root)
    if "README.md" not in files:
        raise CorpusNotFound(f"{root} has no README.md")
    return CorpusReader(source=source, root=root, files=files, commit=manifest.git_head(root))


def _bundled() -> CorpusReader | None:
    try:
        base = resources.files("cpu_perf") / "corpus"
    except (ModuleNotFoundError, TypeError):
        return None
    info_node = base / "_build_info.json"
    try:
        info = json.loads(info_node.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        if not (base / "README.md").is_file():
            return None
        info = {"files": _walk(base)}
    return CorpusReader(
        source="bundled",
        root=base,
        files=sorted(info.get("files") or _walk(base)),
        commit=info.get("commit"),
        built_at=info.get("built_at"),
        commit_date=info.get("commit_date"),
    )


def downloaded(data_dir) -> CorpusReader | None:
    """The newest copy of the list fetched by the daily update, if any."""
    base = Path(data_dir) / "corpus"
    try:
        ptr = json.loads((base / "current.json").read_text(encoding="utf-8"))
        root = base / ptr["sha"]
        info = json.loads((root / "_build_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    files = [f for f in info.get("files", []) if manifest.matches(f) and (root / f).is_file()]
    if "README.md" not in files:
        return None
    return CorpusReader(
        source="downloaded", root=root, files=sorted(files), commit=info.get("commit"),
        built_at=info.get("downloaded_at"), commit_date=info.get("commit_date"),
    )


def _walk(base, prefix: str = "") -> list[str]:
    out = []
    for child in base.iterdir():
        rel = f"{prefix}{child.name}"
        if child.is_dir():
            out.extend(_walk(child, rel + "/"))
        elif child.name != "_build_info.json":
            out.append(rel)
    return out


def locate(explicit: str | os.PathLike | None = None, data_dir: str | os.PathLike | None = None) -> CorpusReader:
    """Explicit path, then CPU_PERF_REPO, then the enclosing checkout, then
    the newer of the wheel's copy and the one the daily update downloaded."""
    explicit = explicit or os.environ.get("CPU_PERF_REPO")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not manifest.is_repo_root(root):
            raise CorpusNotFound(f"{root} is not a checkout of cpu-performance-engineering")
        return _from_dir(root, "explicit")
    root = _checkout_root()
    if root is not None:
        return _from_dir(root, "checkout")
    bundled = _bundled()
    fetched = downloaded(data_dir) if data_dir is not None else None
    if fetched is not None and (bundled is None or fetched.date_key > bundled.date_key):
        return fetched
    if bundled is not None:
        return bundled
    raise CorpusNotFound(
        "no corpus found: install the wheel, run from a checkout, or pass --repo PATH"
    )
